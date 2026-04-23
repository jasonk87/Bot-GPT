import importlib.util
from typing import Dict, List


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def dependency_health_report() -> Dict[str, object]:
    required = {
        "flask": _module_available("flask"),
        "flask_socketio": _module_available("flask_socketio"),
        "flask_login": _module_available("flask_login"),
        "filelock": _module_available("filelock"),
    }
    optional = {
        "dotenv": _module_available("dotenv"),
        "googleapiclient": _module_available("googleapiclient"),
    }

    missing_required: List[str] = [name for name, ok in required.items() if not ok]
    missing_optional: List[str] = [name for name, ok in optional.items() if not ok]

    return {
        "status": "ok" if not missing_required else "degraded",
        "required": required,
        "optional": optional,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
    }
