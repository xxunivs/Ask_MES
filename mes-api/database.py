import pyodbc
import os
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    conn = pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.getenv('DB_SERVER')},{os.getenv('DB_PORT', '1433')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')};"
        f"Connection Timeout=10;"
    )
    return conn
