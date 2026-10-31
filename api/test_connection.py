"""Comprobación manual de solo lectura: python test_connection.py."""
import json
import os
from pathlib import Path

from function_app import with_database

if __name__ == '__main__':
    settings = Path(__file__).with_name('local.settings.json')
    if settings.exists():
        os.environ.update(json.loads(settings.read_text())['Values'])
    count = with_database(lambda conn: conn.cursor().execute(
        'SELECT COUNT(*) FROM kamishibai.maestro_tareas WHERE activo=1'
    ).fetchone()[0])
    print(f'Conexión correcta. Tareas activas: {count}')
