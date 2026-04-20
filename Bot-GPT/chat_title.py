import re
from flask import current_app
from flask_login import current_user
from models import save_conversation
from utils import get_best_default_model


def update_conversation_title(conversation, conversation_path, call_stream, model=None):
    if conversation.get("title") == "New Chat" and len(conversation.get("messages", [])) >= 2:
        try:
            user_message = conversation["messages"][0]["content"]
            assistant_message = next((m["content"] for m in reversed(conversation["messages"]) if m["role"] == "assistant"), "")
            cleaned_content = re.sub(r"<think>[\s\S]*?</think>", "", assistant_message).strip()
            title_prompt = f"Based on the following exchange, create a very short, concise title (5 words or less).\n\nUser: {user_message}\nAssistant: {cleaned_content}\n\nTitle:"
            if not model:
                model = current_user.selected_model or get_best_default_model()
            content = ""
            for chunk in call_stream(model, [{"role": "user", "content": title_prompt}], "You are a helpful assistant."):
                content += chunk
            if content.startswith("Error"):
                current_app.logger.warning(f"AI returned error instead of title: {content}")
                return
            cleaned_title = re.sub(r"<think>[\s\S]*?</think>", "", content.strip()).strip().replace('"', "")
            if cleaned_title:
                conversation["title"] = cleaned_title
                save_conversation(conversation_path, conversation)
        except Exception as e:
            current_app.logger.warning(f"Could not auto-generate title: {e}")
