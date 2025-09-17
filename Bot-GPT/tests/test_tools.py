from unittest.mock import patch
from tools import get_file_tree, request_human_input, query_database


def test_get_file_tree(tmp_path):
    """
    Tests the get_file_tree function to ensure it correctly represents
    a nested directory structure.
    """
    # tmp_path is a pytest fixture providing a temporary directory
    (tmp_path / "file1.txt").touch()
    (tmp_path / "empty_dir").mkdir()
    sub_dir = tmp_path / "sub_dir"
    sub_dir.mkdir()
    (sub_dir / "file2.txt").touch()
    (sub_dir / "another_file.log").touch()

    tree = get_file_tree(str(tmp_path))

    expected_tree = [
        {
            "name": "empty_dir",
            "path": "empty_dir",
            "type": "directory",
            "children": []
        },
        {
            "name": "file1.txt",
            "path": "file1.txt",
            "type": "file"
        },
        {
            "name": "sub_dir",
            "path": "sub_dir",
            "type": "directory",
            "children": [
                {
                    "name": "another_file.log",
                    "path": "sub_dir/another_file.log",
                    "type": "file"
                },
                {
                    "name": "file2.txt",
                    "path": "sub_dir/file2.txt",
                    "type": "file"
                }
            ]
        }
    ]

    # The order of items is not guaranteed, so sort before comparing.
    def sort_tree(t):
        t.sort(key=lambda x: x['name'])
        for item in t:
            if 'children' in item:
                sort_tree(item['children'])

    sort_tree(tree)
    sort_tree(expected_tree)

    assert tree == expected_tree


def test_get_file_tree_on_empty_directory(tmp_path):
    """
    Tests that get_file_tree returns an empty list for an empty directory.
    """
    tree = get_file_tree(str(tmp_path))
    assert tree == []


def test_get_file_tree_on_nonexistent_path():
    """
    Tests that get_file_tree returns an empty list for a path that does not
    exist.
    """
    tree = get_file_tree("a/path/that/does/not/exist")
    assert tree == []


def test_request_human_input():
    """Tests the request_human_input tool."""
    prompt = "What is your name?"
    result = request_human_input(prompt)
    assert result == {
        "status": "human_input_required",
        "prompt": prompt
    }


@patch('tools.get_workspace_path')
def test_query_database(mock_get_workspace_path, tmp_path):
    """Tests the query_database tool."""
    mock_get_workspace_path.return_value = str(tmp_path)

    # Test creating a table and inserting data
    create_query = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"
    result = query_database(create_query, "test_convo", "test_user")
    assert "Query executed successfully" in result

    insert_query = "INSERT INTO users (name) VALUES ('Alice')"
    result = query_database(insert_query, "test_convo", "test_user")
    assert "1 rows affected" in result

    # Test selecting data
    select_query = "SELECT * FROM users"
    result = query_database(select_query, "test_convo", "test_user")
    assert "| id | name |" in result
    assert "| 1 | Alice |" in result

    # Test invalid query
    invalid_query = "SELECT * FROM non_existent_table"
    result = query_database(invalid_query, "test_convo", "test_user")
    assert "Database Error" in result
