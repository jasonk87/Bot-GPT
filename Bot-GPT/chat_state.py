AGENT_SESSIONS = {}


def serialize_agent_session(session):
    if not session or not session.get("running"):
        return None
    return {
        "is_running": True,
        "agent_mode": session.get("agent_mode", False),
        "partial_response": session.get("partial_response", ""),
        "stage": session.get("stage", "thinking"),
        "tool_name": session.get("tool_name"),
        "tool_params": session.get("tool_params"),
        "error": session.get("error"),
    }
