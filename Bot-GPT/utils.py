import os
from flask import current_app

# This file is intentionally left sparse to avoid circular dependencies.
# It can be used for shared constants, simple utility functions, or
# global-like state management that doesn't depend on other parts of the app.

# Example of a shared state dictionary (used by the 'set_plan' tool)
PLAN_APPROVALS = {}

import re

def sanitize_json(json_str):
    """
    Cleans up a JSON string by removing markdown code blocks and
    other common AI formatting artifacts.
    """
    # Remove markdown code blocks
    json_str = re.sub(r"```json\s*", "", json_str)
    json_str = re.sub(r"```\s*", "", json_str)
    return json_str.strip()
