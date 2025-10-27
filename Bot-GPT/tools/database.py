import os
from sqlalchemy import create_engine, inspect
from urllib.parse import quote_plus

def get_db_schema(conversation_id=None, user_id=None):
    """
    Inspects the database and returns its schema.
    """
    from utils import get_workspace_path

    # In a real app, you'd get the db connection info from your app's config
    # For this example, we'll assume the standard SQLite DB location
    instance_path = os.path.join(get_workspace_path(conversation_id, user_id), '..', 'instance')
    db_path = os.path.join(instance_path, 'users.db')

    if not os.path.exists(db_path):
        return f"Error: Database file not found at {db_path}"

    try:
        # The URL needs to be properly escaped
        db_uri = f"sqlite:///{quote_plus(db_path)}"
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
