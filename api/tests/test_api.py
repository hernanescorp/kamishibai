import base64
import json
import sys
import unittest
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import azure.functions as func
import pyodbc
import function_app as api


OWNER = base64.b64encode(json.dumps({'userId': 'test-owner', 'identityProvider': 'github', 'userRoles': ['authenticated', 'propietario']}).encode()).decode()
HEADERS = {'x-ms-client-principal': OWNER}


def request(body):
    return func.HttpRequest(method='POST', url='/api/check', body=json.dumps(body).encode(), headers=HEADERS)


class MemoryCursor:
    def __init__(self):
        self.records = {}
        self.result = None

    def execute(self, sql, *args):
        if sql.startswith('SELECT id_tarea'):
            self.result = (args[0],) if args[0] in range(1, 14) else None
        elif 'INSERT INTO' in sql:
            self.records.setdefault((args[0], args[1]), args[2])
        elif sql.startswith('DELETE'):
            self.records.pop(tuple(args), None)
        elif sql.startswith('SELECT timestamp'):
            stamp = self.records.get(tuple(args))
            self.result = (stamp,) if stamp else None
        return self

    def fetchone(self):
        return self.result


class ApiTests(unittest.TestCase):
    def test_authorization_before_database(self):
        for principal, expected in [(None, 401), ('invalid!', 401), ([], 401),
                ({'userId': 'other', 'identityProvider': 'github', 'userRoles': ['authenticated']}, 403),
                ({'userId': 'other', 'identityProvider': 'aad', 'userRoles': ['authenticated', 'propietario']}, 403),
                ({'userId': 'other', 'identityProvider': 'github', 'userRoles': 'propietario'}, 403)]:
            encoded = principal if isinstance(principal, str) else base64.b64encode(json.dumps(principal).encode()).decode() if principal is not None else None
            headers = {'x-ms-client-principal': encoded} if encoded else {}
            with patch.object(api, 'with_database') as database:
                for handler in (api.tareas, api.check):
                    req = func.HttpRequest(method='GET', url='/', body=b'{}', headers=headers)
                    self.assertEqual(handler(req).status_code, expected)
                database.assert_not_called()

    def test_validation(self):
        for body in ({}, {'id_tarea': True, 'completado': True}, {'id_tarea': 1, 'completado': 1}, [], {'id_tarea': -1, 'completado': False}):
            self.assertEqual(api.check(request(body)).status_code, 400)
        self.assertEqual(api.check(func.HttpRequest(method='POST', url='/', body=b'invalid', headers=HEADERS)).status_code, 400)

    def test_check_idempotency_uncheck_and_history(self):
        cursor = MemoryCursor()
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch.object(api, 'with_database', side_effect=lambda op: op(connection)), patch.object(api, 'today', return_value=date(2026, 10, 31)):
            for _ in range(2):
                result = api.check(request({'id_tarea': 1, 'completado': True, 'fecha': '1999-01-01'}))
                self.assertEqual(result.status_code, 200)
            self.assertEqual(len(cursor.records), 1)
            original = json.loads(result.get_body())['timestamp_completado']
            self.assertTrue(original.endswith('Z'))
            self.assertEqual(api.check(request({'id_tarea': 99, 'completado': True})).status_code, 404)
        with patch.object(api, 'with_database', side_effect=lambda op: op(connection)), patch.object(api, 'today', return_value=date(2026, 11, 1)):
            api.check(request({'id_tarea': 1, 'completado': True}))
            api.check(request({'id_tarea': 1, 'completado': False}))
        self.assertEqual(list(cursor.records), [(1, date(2026, 10, 31))])

    def test_loading_tasks_and_serialization(self):
        connection = Mock()
        rows = [(i, time(i), f'Tarea {i}', None, datetime(2026, 10, 31, 8) if i == 1 else None) for i in range(1, 14)]
        connection.cursor.return_value.execute.return_value.fetchall.return_value = rows
        with patch.object(api, 'with_database', side_effect=lambda op: op(connection)):
            data = json.loads(api.tareas(func.HttpRequest(method='GET', url='/api/tareas', body=b'', headers=HEADERS)).get_body())
        self.assertEqual(len(data['tareas']), 13)
        self.assertTrue(data['tareas'][0]['completado'])
        self.assertFalse(data['tareas'][1]['completado'])
        self.assertIn('ORDER BY t.hora', connection.cursor.return_value.execute.call_args.args[0])

    @patch.dict('os.environ', {'SQL_CONNECTION_STRING': 'fake'})
    @patch.object(api.pyodbc, 'connect')
    def test_one_connection_per_request(self, connect):
        connect.side_effect = [pyodbc.OperationalError('08001', 'unavailable (40613)'), Mock()]
        result = api.database_response(lambda c: 13)
        self.assertEqual(result.status_code, 503)
        self.assertTrue(json.loads(result.get_body())['transitorio'])
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(api.with_database(lambda c: 13), 13)
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(connect.call_args.kwargs['timeout'], 5)

    @patch.dict('os.environ', {'SQL_CONNECTION_STRING': 'fake'})
    @patch.object(api.pyodbc, 'connect')
    def test_permanent_errors_are_not_retryable(self, connect):
        for state in ('28000', '42000', 'IM002'):
            connect.reset_mock()
            connect.side_effect = pyodbc.Error(state, 'permanent error')
            result = api.database_response(lambda c: None)
            self.assertEqual(result.status_code, 500)
            self.assertFalse(json.loads(result.get_body())['transitorio'])
            self.assertEqual(connect.call_count, 1)

    @patch.dict('os.environ', {'SQL_CONNECTION_STRING': 'fake'})
    @patch.object(api.time, 'monotonic', side_effect=[0, 21])
    @patch.object(api.pyodbc, 'connect')
    def test_budget_prevents_late_commit_and_closes(self, connect, clock):
        connection = connect.return_value
        result = api.database_response(lambda c: 13)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(connection.timeout, 3)
        connection.commit.assert_not_called()
        connection.close.assert_called_once()

    def test_madrid_day_and_dst(self):
        for utc, expected in [(datetime(2026, 6, 1, 22, 30), date(2026, 6, 2)), (datetime(2026, 10, 31, 23, 30), date(2026, 11, 1))]:
            with patch.object(api, 'datetime') as clock:
                from datetime import timezone
                clock.now.return_value = utc.replace(tzinfo=timezone.utc).astimezone(api.MADRID)
                self.assertEqual(api.today(), expected)


if __name__ == '__main__':
    unittest.main()
