import chat
import tools


def test_chat_contract_exports():
    assert hasattr(chat, "handle_ai_response")
    assert hasattr(chat, "initialize_chat")
    assert hasattr(chat, "update_conversation_title")
    assert hasattr(chat, "AGENT_SESSIONS")


def test_tools_contract_exports():
    required = [
        "handle_tool_call",
        "call_chat_stream",
        "write_file",
        "list_files",
        "run_shell_command",
    ]
    for name in required:
        assert hasattr(tools, name)


def test_optional_sql_functions_are_callable():
    # Should always be callable even when optional deps are missing.
    assert callable(tools.get_db_schema)
    assert callable(tools.run_sql_query)
