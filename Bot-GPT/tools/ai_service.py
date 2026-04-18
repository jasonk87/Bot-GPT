import os
import json
import requests
from flask import current_app

def call_gemini_chat_stream(model, messages, system_prompt):
    """Calls Google's Gemini API via REST and yields response chunks."""
    print(f"DEBUG: Executing REST API call for model {model}")
    api_key = current_app.config.get("GOOGLE_API_KEY")
    if not api_key:
        yield "Error: GOOGLE_API_KEY not found in configuration."
        return

    # Use REST API URL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={api_key}"
    
    # Prepare contents
    payload = {
        "contents": [],
        "system_instruction": {"parts": [{"text": system_prompt}]}
    }

    import base64

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        images = msg.get("images", [])

        if role == "tool":
            role = "user"
            content = f"Tool Output:\n{content}"
        elif role == "assistant":
            role = "model"
        
        parts = []
        if content:
             parts.append({"text": content})

        for img_path in images:
            if os.path.exists(img_path):
                try:
                    with open(img_path, "rb") as img_f:
                        img_data = base64.b64encode(img_f.read()).decode('utf-8')
                        mime_type = "image/png"
                        if img_path.lower().endswith(".jpg") or img_path.lower().endswith(".jpeg"):
                            mime_type = "image/jpeg"
                        elif img_path.lower().endswith(".webp"):
                            mime_type = "image/webp"
                            
                        parts.append({
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": img_data
                            }
                        })
                except Exception as e:
                    print(f"Error reading image {img_path}: {e}")

        if parts:
             payload["contents"].append({"role": role, "parts": parts})

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            stream=True,
            timeout=300
        )
        response.raise_for_status()

        buffer = ""
        for line in response.iter_lines():
            if not line:
                continue
            
            decoded_line = line.decode('utf-8').strip()
            if not decoded_line:
                continue

            if not buffer:
                if decoded_line == '[': continue
                if decoded_line == ']': continue
                if decoded_line == ',': continue
                if decoded_line.startswith('['): decoded_line = decoded_line[1:].strip()
                elif decoded_line.startswith(','): decoded_line = decoded_line[1:].strip()

            buffer += decoded_line

            try:
                chunk_data = json.loads(buffer)
                buffer = "" 

                candidates = chunk_data.get("candidates", [])
                if candidates:
                    content_parts = candidates[0].get("content", {}).get("parts", [])
                    for part in content_parts:
                        if "text" in part:
                            yield part["text"]
                
                prompt_feedback = chunk_data.get("promptFeedback", {})
                if prompt_feedback.get("blockReason"):
                    yield f"\n[Blocked: {prompt_feedback['blockReason']}]"
                    
            except json.JSONDecodeError:
                continue

    except requests.exceptions.HTTPError as e:
         error_msg = f"Error calling Gemini API: {e}"
         if e.response is not None:
             try:
                 error_msg += f"\nDetails: {e.response.text}"
             except:
                 pass
         yield error_msg
    except Exception as e:
        yield f"Error calling Gemini: {str(e)}"


def call_chat_stream(model, messages, system_prompt):
    """Calls the AI chat API (Ollama or Gemini) and yields response chunks."""
    if "gemini" in model.lower():
        yield from call_gemini_chat_stream(model, messages, system_prompt)
        return

    try:
        ollama_host = current_app.config["OLLAMA_HOST"].rstrip("/")
        if not ollama_host.startswith("http"):
            ollama_host = f"http://{ollama_host}"

        response = requests.post(
            f"{ollama_host}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "system", "content": system_prompt}] + messages,
                "stream": True,
            },
            stream=True,
            timeout=600, # Increased to 10 minutes for slow local models/thinking phases
        )
        response.raise_for_status()

        is_thinking = False
        for byte_line in response.iter_lines():
            if not byte_line:
                continue

            line = byte_line.decode("utf-8")
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[len("data:") :].strip()

            if not line or line == "[DONE]":
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            message_payload = payload.get("message", {})
            content_chunk = message_payload.get("content")
            reasoning_chunk = message_payload.get("reasoning_content")

            # Handle reasoning/thinking content for models like DeepSeek-R1
            if reasoning_chunk:
                if not is_thinking:
                    yield "<think>"
                    is_thinking = True
                yield reasoning_chunk
            
            # When we get actual content, transition out of thinking block if needed
            if content_chunk:
                if is_thinking:
                    yield "</think>"
                    is_thinking = False
                yield content_chunk

            if payload.get("done"):
                if is_thinking:
                    yield "</think>"
                break
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Could not connect to Ollama: {e}") from e
    except Exception as e:
        raise ConnectionError(f"An unexpected error occurred: {e}") from e
