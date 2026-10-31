import json
from pathlib import Path

import pyodbc

settings_path = Path(__file__).parent / "local.settings.json"

with open(settings_path, encoding="utf-8") as f:
    settings = json.load(f)

connection_string = settings["Values"]["SQL_CONNECTION_STRING"]

print("Conectando a Azure SQL Server...")

with pyodbc.connect(connection_string, timeout=30) as conn:
    cursor = conn.cursor()

    cursor.execute("SELECT DB_NAME(), SYSDATETIME()")
    resultado = cursor.fetchone()

    print("Conexion exitosa a Azure SQL Server.")
    print(f"Base de datos: {resultado[0]}, Fecha y hora actual: {resultado[1]}")

    cursor.execute(
        "INSERT INTO kamishibai.registros (valor) VALUES (?)",1
    )

    conn.commit()

    print("Registro insertado correctamente en la tabla 'kamishibai.registros'.")