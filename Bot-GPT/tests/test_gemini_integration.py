from unittest.mock import Mock, patch
from tools.ai_service import call_gemini_chat_stream, call_chat_stream

def test_call_gemini_chat_stream_normal(app):
    with app.app_context():
        app.config["GOOGLE_API_KEY"] = "fake-key"
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            b'{"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}'
        ]
        
        with patch("requests.post", return_value=mock_response) as mock_post:
            res = list(call_gemini_chat_stream("gemini-1.5-flash", [{"role": "user", "content": "hi"}], "sys"))
            assert "".join(res) == "Hello"
            
            # Check payload and URL
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert "gemini-1.5-flash" in args[0]
            assert "key=fake-key" in args[0]
            
            payload = kwargs["json"]
            assert payload["contents"][0]["parts"][0]["text"] == "hi"
            assert "generationConfig" not in payload

def test_call_gemini_chat_stream_max_thinking(app):
    with app.app_context():
        app.config["GOOGLE_API_KEY"] = "fake-key"
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            b'{"candidates": [{"content": {"parts": [{"thought": true, "text": "Thinking..."}, {"text": "Answer"}]}}]}'
        ]
        
        with patch("requests.post", return_value=mock_response) as mock_post:
            res = list(call_gemini_chat_stream("gemini-2.5-flash-lite (Max Thinking)", [{"role": "user", "content": "hi"}], "sys"))
            assert "".join(res) == "<think>Thinking...</think>Answer"
            
            # Check payload and URL
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert "gemini-2.5-flash-lite" in args[0]
            assert " (Max Thinking)" not in args[0]
            
            payload = kwargs["json"]
            assert payload["generationConfig"]["thinkingConfig"]["thinkingBudget"] == -1


def test_call_gemini_chat_stream_function_call(app):
    with app.app_context():
        app.config["GOOGLE_API_KEY"] = "fake-key"
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            b'{"candidates": [{"content": {"parts": [{"functionCall": {"name": "web_search", "args": {"query": "test query"}}}]}}]}'
        ]
        
        with patch("requests.post", return_value=mock_response):
            res = list(call_gemini_chat_stream("gemini-2.5-flash-lite", [{"role": "user", "content": "hi"}], "sys"))
            combined = "".join(res)
            assert "web_search" in combined
            assert "test query" in combined
            assert "tool" in combined
