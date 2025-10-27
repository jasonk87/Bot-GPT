import pytest
from unittest.mock import patch, MagicMock
from tools.sql_query import run_sql_query

# The 'app' fixture is automatically provided by conftest.py and sets up the app context

def test_run_sql_query_success(app):
    """Test that a valid SELECT query executes successfully."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.description = [('id',), ('username',)]
    mock_cursor.fetchall.return_value = [(1, 'testuser'), (2, 'jules')]

    with app.app_context():
        # The tool now correctly uses app.instance_path, so we don't need to set a fake config
        with patch('sqlite3.connect', return_value=mock_conn):
            with patch('os.path.exists', return_value=True):
                result = run_sql_query("SELECT id, username FROM user")

    assert "id, username" in result
    assert "1, testuser" in result
    assert "2, jules" in result
    mock_cursor.execute.assert_called_once_with("SELECT id, username FROM user")

def test_run_sql_query_security_non_select(app):
    """Test that non-SELECT statements are rejected."""
    with app.app_context():
        result = run_sql_query("UPDATE user SET username = 'hacker' WHERE id = 1")
    assert "Error: Only SELECT statements are allowed." in result

def test_run_sql_query_no_results(app):
    """Test that a query with no results returns the correct message."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.description = [('id',), ('username',)]
    mock_cursor.fetchall.return_value = []

    with app.app_context():
        with patch('sqlite3.connect', return_value=mock_conn):
            with patch('os.path.exists', return_value=True):
                result = run_sql_query("SELECT id, username FROM user WHERE username = 'nonexistent'")

    assert "Query executed successfully, but returned no results." in result

def test_run_sql_query_db_not_found(app):
    """Test the case where the database file does not exist."""
    with app.app_context():
        # app.instance_path will be a real path, so we just need to mock os.path.exists
        with patch('os.path.exists', return_value=False):
            result = run_sql_query("SELECT * FROM user")
    assert "Error: Database file not found" in result

def test_run_sql_query_database_error(app):
    """Test that a database error is handled gracefully."""
    with app.app_context():
        with patch('sqlite3.connect') as mock_connect:
            mock_connect.side_effect = Exception("Test DB error")
            with patch('os.path.exists', return_value=True):
                result = run_sql_query("SELECT * FROM user")

    assert "An unexpected error occurred: Test DB error" in result
