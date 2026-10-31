"""HTTP API. SQL stores history; Madrid determines the logical day."""
import base64
import binascii
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import azure.functions as func
import pyodbc

app = func.FunctionApp()
MADRID = ZoneInfo('Europe/Madrid')
CONNECT_TIMEOUT = 5
QUERY_TIMEOUT = 3
DATABASE_BUDGET = 20
TRANSIENT_CODES = {40197, 40501, 40613, 49918, 49919, 49920, 10928, 10929, 1205}


def is_transient(error):
    state = str(error.args[0]) if error.args else ''
    message = ' '.join(map(str, error.args))
    codes = {int(code) for code in re.findall(r'\((\d+)\)', message)}
    # Login, permissions and invalid configuration must fail immediately.
    if state.startswith('28') or codes & {18456, 4060} or any(term in message.lower() for term in ('certificate', 'invalid connection string', 'invalid connection attribute', 'data source name not found')):
        return False
    return state in {'08001', '08003', '08007', '08S01', 'HYT00', 'HYT01'} or bool(codes & TRANSIENT_CODES)


def with_database(operation):
    connection_string = os.environ.get('SQL_CONNECTION_STRING')
    if not connection_string:
        raise RuntimeError('SQL_CONNECTION_STRING no configurada')
    # One attempt per HTTP request. The browser owns progressive retries.
    started = time.monotonic()
    connection = None
    try:
        connection = pyodbc.connect(connection_string, timeout=CONNECT_TIMEOUT)
        connection.timeout = QUERY_TIMEOUT
        result = operation(connection)
        if time.monotonic() - started >= DATABASE_BUDGET:
            raise pyodbc.OperationalError('HYT00', 'Database request budget exhausted')
        connection.commit()
        return result
    finally:
        if connection is not None:
            connection.close()


def today():
    return datetime.now(MADRID).date()


def response(data, status=200):
    return func.HttpResponse(json.dumps(data, ensure_ascii=False), status_code=status, mimetype='application/json')


def require_owner(req):
    """Trust only the principal injected by SWA's managed API gateway.

    This is not a signed token. Never expose this backend independently.
    """
    encoded = req.headers.get('x-ms-client-principal')
    if not encoded:
        return response({'error': 'Inicia sesión para continuar.'}, 401)
    try:
        principal = json.loads(base64.b64decode(encoded, validate=True))
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return response({'error': 'Sesión inválida. Inicia sesión de nuevo.'}, 401)
    if not isinstance(principal, dict) or not principal.get('userId'):
        return response({'error': 'Sesión inválida. Inicia sesión de nuevo.'}, 401)
    roles = principal.get('userRoles')
    if (principal.get('identityProvider') != 'github' or not isinstance(roles, list)
            or 'authenticated' not in roles or 'propietario' not in roles):
        return response({'error': 'Esta cuenta no tiene permiso para acceder.'}, 403)
    return None


def database_response(operation):
    try:
        return response(with_database(operation))
    except pyodbc.Error as error:
        transient = is_transient(error)
        logging.error('Operación SQL fallida; SQLSTATE=%s', error.args[0] if error.args else 'unknown')
        return response({'error': 'La base de datos se está reactivando o no está disponible.' if transient else 'No se pudo acceder a los datos. Revisa la configuración y la migración SQL.', 'transitorio': transient}, 503 if transient else 500)
    except RuntimeError:
        return response({'error': 'El servidor no tiene configurada la conexión a la base de datos.'}, 500)


def serialize_task(row):
    return {'id_tarea': row[0], 'hora': row[1].strftime('%H:%M'), 'nombre': row[2],
            'duracion_minutos': row[3], 'completado': row[4] is not None,
            'timestamp_completado': row[4].isoformat() + 'Z' if row[4] else None}


@app.route(route='tareas', methods=['GET'], auth_level=func.AuthLevel.ANONYMOUS)
def tareas(req: func.HttpRequest) -> func.HttpResponse:
    denied = require_owner(req)
    if denied is not None:
        return denied
    def read(connection):
        date = today()
        rows = connection.cursor().execute('''
            SELECT t.id_tarea, t.hora, t.nombre, t.duracion_minutos, r.timestamp_completado
            FROM kamishibai.maestro_tareas t
            LEFT JOIN kamishibai.registros r ON r.id_tarea=t.id_tarea AND r.fecha=?
            WHERE t.activo=1 ORDER BY t.hora, t.id_tarea
        ''', date).fetchall()
        return {'fecha': date.isoformat(), 'tareas': [serialize_task(row) for row in rows]}
    return database_response(read)


@app.route(route='check', methods=['POST'], auth_level=func.AuthLevel.ANONYMOUS)
def check(req: func.HttpRequest) -> func.HttpResponse:
    denied = require_owner(req)
    if denied is not None:
        return denied
    try:
        body = req.get_json()
    except ValueError:
        return response({'error': 'Se requiere un cuerpo JSON válido.'}, 400)
    if not isinstance(body, dict) or type(body.get('id_tarea')) is not int or not 1 <= body['id_tarea'] <= 2147483647 or type(body.get('completado')) is not bool:
        return response({'error': 'Indica id_tarea entero positivo y completado booleano.'}, 400)

    def write(connection):
        date = today()  # Recomputed after any connection wake-up/retry.
        cursor = connection.cursor()
        if not cursor.execute('SELECT id_tarea FROM kamishibai.maestro_tareas WHERE id_tarea=? AND activo=1', body['id_tarea']).fetchone():
            return {'error': 'La tarea no existe o está inactiva.', '_status': 404}
        if body['completado']:
            cursor.execute('''
                INSERT INTO kamishibai.registros (id_tarea, fecha, timestamp_completado)
                SELECT ?, ?, ? WHERE NOT EXISTS (
                    SELECT 1 FROM kamishibai.registros WITH (UPDLOCK, HOLDLOCK)
                    WHERE id_tarea=? AND fecha=?)
            ''', body['id_tarea'], date, datetime.now(timezone.utc).replace(tzinfo=None), body['id_tarea'], date)
        else:
            cursor.execute('DELETE FROM kamishibai.registros WHERE id_tarea=? AND fecha=?', body['id_tarea'], date)
        row = cursor.execute('SELECT timestamp_completado FROM kamishibai.registros WHERE id_tarea=? AND fecha=?', body['id_tarea'], date).fetchone()
        return {'id_tarea': body['id_tarea'], 'fecha': date.isoformat(), 'completado': bool(row),
                'timestamp_completado': row[0].isoformat() + 'Z' if row else None}
    result = database_response(write)
    if result.status_code == 200:
        data = json.loads(result.get_body())
        return response(data, data.pop('_status', 200))
    return result
