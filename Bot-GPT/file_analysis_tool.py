import pandas as pd
import os
from utils import get_workspace_path

def file_analysis_tool(filename: str, conversation_id: str, user_id: str):
    """
    Reads a CSV file from the workspace, analyzes it, and returns a summary.
    The summary includes the column names and the first 5 rows of data.
    """
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    filepath = os.path.join(workspace_path, filename)

    if not os.path.exists(filepath):
        return f"Error: File '{filename}' not found in the workspace."

    try:
        df = pd.read_csv(filepath)
        summary = {
            "columns": df.columns.tolist(),
            "head": df.head().to_dict(orient='records')
        }
        return f"Successfully analyzed '{filename}'.\nColumns: {summary['columns']}\nFirst 5 rows:\n{df.head().to_string()}"
    except Exception as e:
        return f"Error analyzing file: {e}"
