import os
import requests
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

def get_best_default_model():
    """
    Determines the best default model based on Ollama availability.
    Prioritizes gemma4:e2b, then any available Ollama model.
    """
    try:
        ollama_host = current_app.config.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        if not ollama_host.startswith("http"):
            ollama_host = f"http://{ollama_host}"
        
        response = requests.get(f"{ollama_host}/api/tags", timeout=5)
        if response.ok:
            available_models = [m.get("name") for m in response.json().get("models", [])]
            if not available_models:
                return "gemma4:e2b" # Fallback guess
            
            if "gemma4:e2b" in available_models:
                return "gemma4:e2b"
            
            # If gemma4:e2b not found, return the first one
            return available_models[0]
    except Exception:
        pass
    
    return "gemma4:e2b"
