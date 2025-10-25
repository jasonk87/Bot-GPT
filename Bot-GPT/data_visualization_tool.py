import pandas as pd
import matplotlib.pyplot as plt
import os
from flask import current_app

def data_visualization_tool(df: pd.DataFrame, chart_type: str, title: str, xlabel: str, ylabel: str):
    """
    Generates a data visualization from a pandas DataFrame and saves it as an image.
    Supported chart types: 'bar', 'line', 'pie'.
    Returns the path to the saved image.
    """
    if not isinstance(df, pd.DataFrame):
        return "Error: Input data must be a pandas DataFrame."

    if chart_type not in ['bar', 'line', 'pie']:
        return "Error: Unsupported chart type. Please use 'bar', 'line', or 'pie'."

    # Ensure the directory for visualizations exists
    viz_dir = os.path.join(current_app.static_folder, 'visualizations')
    os.makedirs(viz_dir, exist_ok=True)

    plt.figure()
    if chart_type == 'bar':
        df.plot(kind='bar')
    elif chart_type == 'line':
        df.plot(kind='line')
    elif chart_type == 'pie':
        # Pie chart is suitable for a single series of data
        if df.shape[1] == 1:
            df.iloc[:, 0].plot(kind='pie', autopct='%1.1f%%')
        else:
            # If multiple columns, use the first one
            df.iloc[:, 0].plot(kind='pie', autopct='%1.1f%%')

    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)

    # Save the plot to a file
    filename = f"{title.replace(' ', '_').lower()}_{chart_type}.png"
    filepath = os.path.join(viz_dir, filename)
    plt.savefig(filepath)
    plt.close()

    return {"type": "visualization", "path": f"/static/visualizations/{filename}"}
