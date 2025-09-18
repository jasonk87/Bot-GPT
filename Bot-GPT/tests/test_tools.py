from unittest.mock import patch
from tools import (
    get_file_tree, request_human_input, query_database,
    save_memory, recall_memory, search_memories, delete_memory,
    summarize_and_save_memory
)


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


def test_save_and_recall_memory(app, test_user, cleanup_chroma):
    """Tests saving and recalling a memory."""
    with app.app_context():
        # Save a new memory
        result = save_memory("test_key", "test_value", user_id=test_user.id)
        assert result == "Memory 'test_key' saved."

        # Recall the memory
        result = recall_memory("test_key", user_id=test_user.id)
        assert result == "test_value"

        # Overwrite the memory
        result = save_memory("test_key", "new_value", user_id=test_user.id)
        assert result == "Memory 'test_key' saved."

        # Recall the overwritten memory
        result = recall_memory("test_key", user_id=test_user.id)
        assert result == "new_value"


def test_search_memories(app, test_user, cleanup_chroma):
    """Tests searching for memories."""
    with app.app_context():
        save_memory("color", "My favorite color is blue.", user_id=test_user.id)
        save_memory("food", "My favorite food is pizza.", user_id=test_user.id)

        # Search for a specific memory
        result = search_memories("blue", user_id=test_user.id)
        assert "color: My favorite color is blue." in result

        # Search for another memory
        result = search_memories("pizza", user_id=test_user.id)
        assert "food: My favorite food is pizza." in result

        # Search for a non-existent memory
        result = search_memories("green", user_id=test_user.id)
        assert result == "No memories found matching the query."


def test_delete_memory(app, test_user, cleanup_chroma):
    """Tests deleting a memory."""
    with app.app_context():
        save_memory("to_delete", "This will be deleted.", user_id=test_user.id)

        # Delete the memory
        result = delete_memory("to_delete", user_id=test_user.id)
        assert result == "Memory 'to_delete' deleted."

        # Try to recall the deleted memory
        result = recall_memory("to_delete", user_id=test_user.id)
        assert result == "No memory found for key 'to_delete'."

        # Try to delete a non-existent memory
        result = delete_memory("non_existent", user_id=test_user.id)
        assert result == "No memory found for key 'non_existent'."


@patch('tools.requests.post')
def test_summarize_and_save_memory(mock_post, app, test_user, cleanup_chroma):
    """Tests summarizing and saving a memory."""
    with app.app_context():
        # Mock the response from the Ollama API
        mock_post.return_value.json.return_value = {
            "message": {
                "content": "This is a summary."
            }
        }
        mock_post.return_value.raise_for_status.return_value = None

        # Summarize and save a new memory
        result = summarize_and_save_memory(
            "This is a long piece of text to summarize.",
            user_id=test_user.id,
            user=test_user
        )
        assert result == "Memory 'This is a summary.' saved."

        # Recall the memory
        result = recall_memory("This is a summary.", user_id=test_user.id)
        assert result == "This is a long piece of text to summarize."
