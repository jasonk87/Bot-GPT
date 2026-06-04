import os
from sqlalchemy import create_engine, inspect
from urllib.parse import quote_plus

from flask import current_app

def get_db_schema(conversation_id=None, user_id=None):
    """
    Inspects the database and returns its schema.
    """
    # Get the path to the database from the app's instance path
    db_path = os.path.join(current_app.instance_path, 'users.db')

    if not os.path.exists(db_path):
        return f"Error: Database file not found at {db_path}"

    try:
        # Convert path to a clean SQLite URI
        # Replacing backslashes with forward slashes is standard for file URIs in SQLAlchemy
        clean_path = db_path.replace(os.sep, '/')
        db_uri = f"sqlite:///{clean_path}"
        engine = create_engine(db_uri)
        inspector = inspect(engine)

        schema_info = ""
        tables = inspector.get_table_names()
        if not tables:
            return "Database is empty."

        for table_name in tables:
            schema_info += f"Table: {table_name}\n"
            columns = inspector.get_columns(table_name)
            for column in columns:
                schema_info += f"  - {column['name']} ({column['type']})\n"
            schema_info += "\n"

        return schema_info

    except Exception as e:
        return f"Error inspecting database schema: {str(e)}"
