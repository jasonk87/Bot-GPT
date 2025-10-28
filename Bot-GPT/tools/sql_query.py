import os
import sqlite3
from flask import current_app

def run_sql_query(query, conversation_id=None, user_id=None):
    """
    Executes a read-only SQL query against the application's database.
    Only SELECT statements are allowed.
    """
    # Security check: only allow SELECT statements
    if not query.strip().upper().startswith("SELECT"):
        return "Error: Only SELECT statements are allowed."

    try:
        # Get the path to the database from the app's instance path
        db_path = os.path.join(current_app.instance_path, 'users.db')

        if not os.path.exists(db_path):
            return f"Error: Database file not found at {db_path}"

        # Connect to the SQLite database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Execute the query
        cursor.execute(query)

        # Fetch results
        rows = cursor.fetchall()

        # Get column names
        column_names = [description[0] for description in cursor.description]

        # Close the connection
        conn.close()

        # Format the results
        if not rows:
            return "Query executed successfully, but returned no results."

        result_str = ", ".join(column_names) + "\n"
        for row in rows:
            result_str += ", ".join(map(str, row)) + "\n"

        return result_str

    except sqlite3.Error as e:
        return f"Database error: {e}"
    except Exception as e:
        return f"An unexpected error occurred: {e}"
