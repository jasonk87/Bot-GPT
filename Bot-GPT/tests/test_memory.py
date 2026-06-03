import os

from memory import MemoryManager
from tools.file_system import get_workspace_path


class FakeCollection:
    def __init__(self):
        self.calls = []

    def upsert(self, ids, documents, metadatas):
        self.calls.append({
            "ids": ids,
            "documents": documents,
            "metadatas": metadatas,
        })


class FakeChromaClient:
    def __init__(self):
        self.collection_names = []

    def get_or_create_collection(self, name):
        self.collection_names.append(name)
        return {"name": name}


def test_archive_conversation_persists_only_user_turns():
    memory = MemoryManager()
    memory.user_collection = FakeCollection()

    archived = memory.archive_conversation({
        "id": "convo-123",
        "messages": [
            {"role": "user", "content": "My name is Jason and I like dark roast coffee."},
            {"role": "assistant", "content": "<think>hidden</think>I'll remember that."},
            {"role": "tool", "content": "ignore me"},
        ],
    })

    assert archived == 1
    assert len(memory.user_collection.calls) == 1
    assert memory.user_collection.calls[0]["ids"] == ["conversation:convo-123:0:user"]
    assert memory.user_collection.calls[0]["documents"] == ["user: My name is Jason and I like dark roast coffee."]


def test_project_memory_uses_same_collection_for_same_repo_remote(app, test_user):
    with app.app_context():
        first_workspace = get_workspace_path("convo-a", test_user.id)
        second_workspace = get_workspace_path("convo-b", test_user.id)

        for workspace in (first_workspace, second_workspace):
            repo_git_dir = os.path.join(workspace, "repo", ".git")
            os.makedirs(repo_git_dir, exist_ok=True)
            with open(os.path.join(repo_git_dir, "config"), "w", encoding="utf-8") as handle:
                handle.write('[remote "origin"]\n\turl = https://github.com/example/shared-repo.git\n')

        memory = MemoryManager()
        memory.chroma_client = FakeChromaClient()

        memory.set_project_memory_file(test_user.id, "convo-a")
        memory.set_project_memory_file(test_user.id, "convo-b")

        assert len(memory.chroma_client.collection_names) == 2
        assert memory.chroma_client.collection_names[0] == memory.chroma_client.collection_names[1]


def test_project_memory_falls_back_to_shared_owner_collection_without_repo(app, test_user):
    with app.app_context():
        get_workspace_path("plain-a", test_user.id)
        get_workspace_path("plain-b", test_user.id)

        memory = MemoryManager()
        memory.chroma_client = FakeChromaClient()

        memory.set_project_memory_file(test_user.id, "plain-a")
        memory.set_project_memory_file(test_user.id, "plain-b")

        assert memory.chroma_client.collection_names == [
            "project_memory_user-default_1",
            "project_memory_user-default_1",
        ]


def test_runtime_remember_tool_dispatches_correctly(app, test_user, mocker):
    from unittest.mock import MagicMock
    mock_memory = MagicMock()
    mocker.patch("memory.MemoryManager", return_value=mock_memory)

    from tools.runtime import remember, recall, forget

    # Test remember user scope
    remember(scope="user", key="k1", value="v1", user_id=test_user.id)
    mock_memory.remember.assert_called_once_with("user", "k1", "v1")

    # Test remember project scope
    mock_memory.reset_mock()
    remember(
        scope="project",
        key="k2",
        value="v2",
        conversation_id="convo-x",
        user_id=test_user.id,
        owner_id=test_user.id,
        project_id="proj-y"
    )
    mock_memory.set_project_memory_file.assert_called_once_with(test_user.id, "convo-x", project_id="proj-y")
    mock_memory.remember.assert_called_once_with("project", "k2", "v2")

    # Test recall
    mock_memory.reset_mock()
    recall(
        scope="project",
        key="k2",
        conversation_id="convo-x",
        user_id=test_user.id,
        owner_id=test_user.id,
        project_id="proj-y"
    )
    mock_memory.set_project_memory_file.assert_called_once_with(test_user.id, "convo-x", project_id="proj-y")
    mock_memory.recall.assert_called_once_with("project", "k2")

    # Test forget
    mock_memory.reset_mock()
    forget(
        scope="project",
        key="k2",
        conversation_id="convo-x",
        user_id=test_user.id,
        owner_id=test_user.id,
        project_id="proj-y"
    )
    mock_memory.set_project_memory_file.assert_called_once_with(test_user.id, "convo-x", project_id="proj-y")
    mock_memory.forget.assert_called_once_with("project", "k2")

