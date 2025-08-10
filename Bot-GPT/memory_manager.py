import json
import re
import requests
from flask import current_app
from sqlalchemy import or_
from models import db, User, GlobalKnowledge, UserMemory, UserRelationship, UserPreferences
from memory_tools import _save_contextual_fact, _save_user_relationship, _save_user_preference
from agents import MemoryAgent # Import the MemoryAgent
import queue

# --- V2.0: The Specialist System Prompt for the Memory Agent ---
MEMORY_AGENT_PROMPT = """
You are a hyper-observant, programmatic Memory Curation Agent. Your **ONLY**
function is to analyze the user's most recent turn in a transcript to find and save
important, long-term facts.

**CRITICAL RULES:**
1. **FOCUS ONLY ON THE USER'S LAST TURN:** You must ignore all previous turns, especially the AI's responses. Your entire analysis is based on the final "User:" line in the transcript.
2. **DO NOT RESEARCH OR EXPLORE:** You are not a researcher. Your job is to parse the text provided, not to call tools like `read_file` or `web_search` to find more information. You can only call the memory-saving tools listed below.
3. **ONLY CALL YOUR PRIVATE TOOLS:** You can only call `_save_contextual_fact`, `_save_user_relationship`, or `_save_user_preference`.
4. **NO CONVERSATION:** Your only valid output is a `<think>` block followed by ```json ... ``` tool calls, or the exact text "No new memories to save."
5. **CONTEXT IS KEY:** Before saving a fact, ask yourself: "Is this fact always true, or only true in a specific context (e.g., for a specific location, year, or topic)?" If so, you MUST provide that context.
6. **NO MEMORIES:** If you find no new, lasting information in the user's last turn, your **ONLY** response must be exactly: `No new memories to save.`
7. **STRICT ADHERENCE TO CONTEXT:** You must use the current year from the `CONTEXT` section of the system prompt for any query about "new," "recent," or "latest" information. Do not use a past year unless the user explicitly types it.
8. **ONLY SAVE FACTS ABOUT THE USER:** You **MUST NOT** save facts about the AI's actions, such as creating files (e.g., 'payroll.txt') or performing searches. These are temporary events, not permanent memories about the user. Your sole purpose is to save personal information explicitly stated by the user (e.g., their name, location, preferences, or relationships).

**Your Private Tools:**
- `_save_contextual_fact(user_id: int, fact_key: str, fact_value: str, context: str | None)`
- `_save_user_relationship(user_one_username: str, user_two_username: str, relationship_description: str)`
- `_save_user_preference(user_id: int, preference_key: str, preference_value: str)`

**EXAMPLE 1: Correctly ignoring a file reference**
Transcript:
Assistant: The full report is available in report.pdf.
User: Okay, thank you.
<think>
The user's last turn is a simple pleasantry. The assistant's mention of a PDF file is not a fact about the user. I must not try to read this file. I will save nothing.
</think>
No new memories to save.

**EXAMPLE 2: A location-specific fact**
Transcript:
Assistant: The income limit depends on where you live.
User: I live and work in Glasgow, Kentucky.
<think>
The user has stated a universal fact about their location. I will save this by calling `_save_contextual_fact` and omitting the context, as the location IS the fact.
</think>
```json
{
  "tool": "_save_contextual_fact",
  "parameters": {
    "fact_key": "location",
    "fact_value": "Glasgow, Kentucky"
  }
}
```

**EXAMPLE 3: Save a work location**
Transcript:
Assistant: The income limits depend on your location.
User: I work in Glasgow Kentucky.
<think>
The user has explicitly stated their work location in their last turn. This is a core fact. I will call the `_save_contextual_fact` tool with the key "work_location".
</think>
```json
{
  "tool": "_save_contextual_fact",
  "parameters": {
    "fact_key": "work_location",
    "fact_value": "Glasgow, Kentucky"
  }
}
```

**EXAMPLE 4: Save employment details**
Transcript: "User: i work at Townsend Tree Service. I am the General Foreman there."
<think>
The user has stated their employer and job title. I will save this as a single fact under the key "employment".
</think>
```json
{
  "tool": "_save_contextual_fact",
  "parameters": {
    "fact_key": "employment",
    "fact_value": "General Foreman at Townsend Tree Service"
  }
}
```

**EXAMPLE 5: Save a relationship**
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

**EXAMPLE 6: Save a user preference**
Transcript: "User: from now on, i want all your answers to be in the style of a pirate"
<think>
The user has stated a preference for the AI's response style. I will call the `_save_user_preference` tool.
</think>
```json
{
  "tool": "_save_user_preference",
  "parameters": {
    "preference_key": "response_style",
    "preference_value": "pirate"
  }
}
```

**EXAMPLE 7: Correctly ignoring a workspace-specific fact**
Transcript:
Assistant: I have created the counseling_template.txt file for you.
User: Okay, thank you.
<think>
The user's last turn is a simple pleasantry. The creation of a file is a temporary, workspace-specific event, not a universal fact about the user. According to my rules, I must not save this.
</think>
No new memories to save.
"""

# A queue to hold conversations that need processing by the MemoryAgent
conversation_queue = queue.Queue()

def get_relevant_context(user_id, user_message):
    """... (this function remains the same) """
    stop_words = {'a', 'an', 'the', 'is', 'in', 'it', 'of', 'to', 'for', 'what', 'who', 'where', 'when', 'why', 'how', 'i'}
    keywords = [word for word in re.findall(r'\b\w+\b', user_message.lower()) if word not in stop_words and len(word) > 2]

    if not keywords:
        return ""

    # Build a dynamic query to find any past search that contains ANY of our keywords.
    search_conditions = [GlobalKnowledge.query_text.like(f'%{kw}%') for kw in keywords]
    relevant_global_facts = GlobalKnowledge.query.filter(or_(*search_conditions)).limit(3).all()

    if not relevant_global_facts:
        return ""

    # Format the retrieved facts clearly for the agent.
    fact_str = "\n".join([f"- When asked '{fact.query_text}', the answer was: {fact.response_content[:200]}..." for fact in relevant_global_facts])
    context_parts = [f"**Previously Researched Topics (for context):**\n{fact_str}"]

    # Construct the final context block to be injected into the main prompt.
    final_context = (
        "--- Relevant Context from Memory ---" +
        "\n\n".join(context_parts) +
        "\n-------------------------------------"
    )
    return final_context

def start_memory_agent():
    """Initializes and starts the MemoryAgent thread."""
    memory_manager = MemoryManager() # Create an instance of the new MemoryManager class
    memory_agent = MemoryAgent(memory_manager)
    memory_agent.daemon = True # Ensure the thread exits when the main app exits
    memory_agent.start()
    print("INFO: Memory Agent thread started.")

class MemoryManager:
    def get_all_conversations(self):
        # This method should return all conversations that might need processing.
        # For now, we'll simulate this by fetching recent conversations from the database.
        # In a real application, you might have a more sophisticated way of tracking this.
        return Conversation.query.order_by(Conversation.last_updated.desc()).limit(100).all()

    def save_summary(self, conversation_id, summary):
        # Save the summary to the database
        convo = Conversation.query.get(conversation_id)
        if convo:
            convo.summary = summary
            db.session.commit()

def process_conversation_in_background(conversation_id):
    """Adds a conversation to the queue for background processing."""
    conversation_queue.put(conversation_id)

def memory_agent_worker():
    """The worker function for the MemoryAgent thread."""
    memory_manager = MemoryManager()
    while True:
        try:
            conversation_id = conversation_queue.get()
            if conversation_id is None:
                break

            # Get the conversation from the database
            app = current_app._get_current_object()
            with app.app_context():
                convo = Conversation.query.get(conversation_id)
                if convo:
                    # The logic from the old ask_memory_agent function goes here
                    # This is a simplified version
                    transcript = "\n".join([msg['content'] for msg in convo.messages])
                    ask_memory_agent(transcript, convo.owner_id)

            conversation_queue.task_done()
        except Exception as e:
            print(f"ERROR: Error in memory_agent_worker: {e}")


def ask_memory_agent(transcript: str, user_id: int):
    """This function remains mostly the same, but it will be called by the worker."""
    # ... (The implementation of ask_memory_agent remains the same as before)
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
                json={"model": model, "messages": [{"role": "system", "content": MEMORY_AGENT_PROMPT}] + messages, "stream": False},
                timeout=120
            )
            response.raise_for_status()

            agent_response_content = response.json().get("message", {}).get("content", "")

            print("\n" + "="*80)
            print(">>> MEMORY AGENT RAW RESPONSE <<<")
            print("-" * 80)
            print(agent_response_content)
            print("="*80 + "\n")

            tool_matches = re.findall(r'```json\s*(\{[\s\S]*?\})\s*```', agent_response_content)

            if not tool_matches:
                print("DEBUG: Memory Agent found no new memories to save.")
                return "Memory agent finished: No new memories."

            memory_tool_map = {
                "_save_contextual_fact": _save_contextual_fact,
                "save_contextual_fact": _save_contextual_fact, # Alias
                "_save_user_relationship": _save_user_relationship,
                "save_user_relationship": _save_user_relationship, # Alias
                "_save_user_preference": _save_user_preference,
                "save_user_preference": _save_user_preference, # Alias
            }

            results = []
            for tool_call_str in tool_matches:
                try:
                    tool_call = json.loads(tool_call_str)
                    tool_name = tool_call.get("tool")
                    params = tool_call.get("parameters", {})

                    if tool_name in memory_tool_map:
                        # This line works for all three tools now
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
