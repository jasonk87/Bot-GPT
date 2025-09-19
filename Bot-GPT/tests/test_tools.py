from tools import get_file_tree


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
