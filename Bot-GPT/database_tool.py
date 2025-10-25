from extensions import db
import pandas as pd
from sqlalchemy import text

def database_tool(query: str):
    """
    Executes a read-only SQL query against the database and returns the results as a pandas DataFrame.
    Only SELECT statements are allowed.
    """
    if not query.strip().upper().startswith('SELECT'):
        raise ValueError("Only SELECT statements are allowed.")

    try:
        with db.engine.connect() as connection:
            result = connection.execute(text(query))
            df = pd.DataFrame(result.fetchall(), columns=result.keys())
            return df
    except Exception as e:
        return f"An error occurred: {e}"
