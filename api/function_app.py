import os
import azure.functions as func
import pyodbc

app = func.FunctionApp() # Create an instance of the FunctionApp class

@app.route(
    route="check", 
    methods=["POST"], # Define the route and HTTP method for the function
    auth_level=func.AuthLevel.ANONYMOUS
    )
def check(req: func.HttpRequest) -> func.HttpResponse: # Define the function that will be executed when the route is accessed

    with pyodbc.connect(os.environ["SQL_CONNECTION_STRING"], timeout=30) as conn:
        cursor = conn.cursor() # Create a cursor object to execute SQL queries, CURSOR is a pointer that allows you to traverse the records in a database
        cursor.execute(
            "INSERT INTO kamishibai.registros (valor) VALUES (?)",1
        )
        conn.commit()
    return func.HttpResponse("CHECK guardado", status_code=200) # Return a response indicating that the record was saved successfully