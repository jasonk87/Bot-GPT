import json
import re
import requests
from flask import current_app
from models import (db, User, GlobalKnowledge, UserMemory, 
                    UserRelationship, UserPreferences)
from memory_tools import _save_user_fact, _save_user_relationship, _save_user_preference

# --- V2.0: The Specialist System Prompt for the Memory Agent ---
# --- V2.0: The Specialist System Prompt for the Memory Agent ---
MEMORY_AGENT_PROMPT = """
You are a hyper-observant, programmatic Memory Curation Agent. Your **ONLY**
function is to analyze a transcript and call tools to save important, long-term
information. You **MUST NOT** respond conversationally. Your **ONLY** valid
output is either a `<think>` block followed by one or more ```json ... ```
tool calls, or the exact text "No new memories to save."

**CRITICAL RULES:**
1. **ONLY CALL TOOLS:** If you find a new fact, preference, or relationship in the transcript that is a declarative statement from the user, you **MUST** call the appropriate tool.
2. **NO CONVERSATION:** Do not say "I have saved..." or ask clarifying questions. Your job is to parse and execute.
3. **STRICT OUTPUT FORMAT:** Your entire response **MUST** be a `<think>` block explaining your reasoning, followed by one or more ```json ... ``` blocks for each tool you need to call.
4. **BE CONSERVATIVE:** Do not save trivial details, questions, or conversational pleasantries. Only save core, reusable facts explicitly stated by the user.
5. **NO MEMORIES:** If you find no new, lasting information worth saving, your **ONLY** response must be exactly: `No new memories to save.`

**Your Private Tools:**
- `_save_user_fact(user_id: int, fact_key: str, fact_value: str)`
- `_save_user_relationship(user_one_username: str, user_two_username: str, relationship_description: str)`
- `_save_user_preference(user_id: int, preference_key: str, preference_value: str)`

**EXAMPLE 1: Save a name**
Transcript: "User: my name is jason kinslow"
<think>
The user has stated their name is "jason kinslow". This is a permanent fact. I will call the `_save_user_fact` tool with the key "name".
</think>
```json
{
  "tool": "_save_user_fact",
  "parameters": {
    "fact_key": "name",
    "fact_value": "jason kinslow"
  }
}
```

**EXAMPLE 2: Save employment details**
Transcript: "User: i work at Townsend Tree Service. I am the General Foreman there."
<think>
The user has stated their employer and job title. I will save this as a single fact under the key "employment".
</think>
```json
{
  "tool": "_save_user_fact",
  "parameters": {
    "fact_key": "employment",
    "fact_value": "General Foreman at Townsend Tree Service"
  }
}
```

**EXAMPLE 3: Save a relationship**
Transcript: "User: my wife's username is jason_king"
<think>
The user has described a relationship with another user. I must call the `_save_user_relationship` tool using the current user's username from context.
</think>
```json
{
  "tool": "_save_user_relationship",
  "parameters": {
    "user_one_username": "TheStarlord0841",
    "user_two_username": "jason_king",
    "relationship_description": "is the husband of"
  }
}
```
"""


def get_relevant_context(user_id, user_message):
    """
    The core of the RAG pipeline for V2.0.
    This function retrieves relevant facts from all memory layers
    and formats them for injection into the agent's main prompt.
    """
    
    context_parts = []
    
    user = User.query.get(user_id)
    if not user:
        return ""

    # --- Layer 1: User-Specific Facts ---
    personal_facts = UserMemory.query.filter_by(user_id=user_id).all()
    if personal_facts:
        fact_str = "\n".join([f"- {fact.fact_key}: {fact.fact_value}" for fact in personal_facts])
        context_parts.append(f"**Personal Facts about {user.username}:**\n{fact_str}")

    # --- Layer 2: User Relationships ---
    relationships = UserRelationship.query.filter(
        (UserRelationship.user_one_id == user_id) | (UserRelationship.user_two_id == user_id)
    ).all()
    if relationships:
        rel_str_parts = []
        for rel in relationships:
            if rel.user_one_id == user_id:
                partner = User.query.get(rel.user_two_id)
                if partner:
                    rel_str_parts.append(f"- Your {rel.relationship_description.replace('is the ', '').replace(' of', '')} is {partner.username}")
            else:
                partner = User.query.get(rel.user_one_id)
                if partner:
                    rel_str_parts.append(f"- {partner.username}'s {rel.relationship_description.replace('is the ', '').replace(' of', '')} is you")
        if rel_str_parts:
            context_parts.append(f"**Your Relationships:**\n" + "\n".join(rel_str_parts))

    # --- Layer 3: User Preferences ---
    preferences = UserPreferences.query.filter_by(user_id=user_id).all()
    if preferences:
        pref_str = "\n".join([f"- {pref.preference_key}: {pref.preference_value}" for pref in preferences])
        context_parts.append(f"**Your Preferences:**\n{pref_str}")

    # --- V2.0 FIX: Activate Global Knowledge Retrieval ---
    global_facts = GlobalKnowledge.query.all()
    if global_facts:
        home_location = next((fact.response_content for fact in global_facts if fact.query_text == "home_location"), None)
        if home_location:
             context_parts.append(f"**Global Shared Facts:**\n- The family's home location is: {home_location}")

    if not context_parts:
        return ""

    final_context = (
        "--- Relevant Context from Memory ---\n"
        + "\n\n".join(context_parts)
        + "\n-------------------------------------\n"
    )
    return final_context

def ask_memory_agent(transcript: str, user_id: int):
    """
    The entry point for the specialist Memory Agent. This function is called
    in the background to analyze and save memories from a conversation.
    """
    from app import create_app
    app = create_app()
    with app.app_context():
        print(f"DEBUG: Memory Agent started for user {user_id}.")

        analysis_prompt = f"Here is a recent conversation transcript for user ID {user_id}. Please analyze it and save any important facts, relationships, or preferences:\n\n{transcript}"
        
        messages = [{"role": "user", "content": analysis_prompt}]
        
        try:
            ollama_host = current_app.config['OLLAMA_HOST']
            user = User.query.get(user_id)
            model = user.selected_model if user and user.selected_model else 'default_model_name'

            response = requests.post(
                f"{ollama_host}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": MEMORY_AGENT_PROMPT}] + messages,
                    "stream": False
                },
                timeout=120
            )
            response.raise_for_status()
            
            agent_response_content = response.json().get("message", {}).get("content", "")
            print(f"DEBUG: Memory Agent Response: {agent_response_content}")

            tool_matches = re.findall(r'```json\s*(\{[\s\S]*?\})\s*```', agent_response_content)
            
            if not tool_matches:
                print("DEBUG: Memory Agent found no new memories to save.")
                return "Memory agent finished: No new memories."

            memory_tool_map = {
                "_save_user_fact": _save_user_fact,
                "_save_user_relationship": _save_user_relationship,
                "_save_user_preference": _save_user_preference,
            }

            results = []
            for tool_call_str in tool_matches:
                try:
                    tool_call = json.loads(tool_call_str)
                    tool_name = tool_call.get("tool")
                    params = tool_call.get("parameters", {})
                    
                    if tool_name in memory_tool_map:
                        if 'user_id' in params or tool_name in ['_save_user_fact', '_save_user_preference']:
                            params['user_id'] = user_id
                        
                        tool_func = memory_tool_map[tool_name]
                        result = tool_func(**params)
                        results.append(result)
                    else:
                        results.append(f"Error: Memory agent tried to call unknown tool '{tool_name}'.")
                except Exception as e:
                    results.append(f"Error processing memory tool call: {e}")

            final_report = "\n".join(results)
            print(f"DEBUG: Memory Agent finished. Report:\n{final_report}")
            return final_report

        except Exception as e:
            error_message = f"Error during Memory Agent execution: {e}"
            print(f"ERROR: {error_message}")
            return error_message