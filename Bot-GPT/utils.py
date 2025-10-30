import os
from flask import current_app

# This file is intentionally left sparse to avoid circular dependencies.
# It can be used for shared constants, simple utility functions, or
# global-like state management that doesn't depend on other parts of the app.

# Example of a shared state dictionary (used by the 'set_plan' tool)
PLAN_APPROVALS = {}
