import requests
from bs4 import BeautifulSoup
from flask import current_app

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except Exception:  # optional dependency in some environments
    build = None

    class HttpError(Exception):
        pass


def _google_client_available():
    return build is not None


def google_search(api_key, cse_id, query):
    """Performs a Google search and returns the results."""
    if not _google_client_available():
        raise ConnectionError(
            "Google search dependency unavailable: install 'google-api-python-client'."
        )
    try:
        service = build("customsearch", "v1", developerKey=api_key)
        res = service.cse().list(q=query, cx=cse_id, num=3).execute()  # pylint: disable=no-member
        return res.get("items", [])
    except HttpError as e:
        raise ConnectionError(
            f"Google Search API HTTP error: {e.content.decode('utf-8')}"
        ) from e
    except Exception as e:
        raise ConnectionError(
            f"An unexpected error occurred during Google search: {e}"
        ) from e


def scrape_text_from_url(url):
    """Scrapes text content from a URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        return "\n".join(chunk for chunk in chunks if chunk)
    except requests.exceptions.RequestException as e:
        return f"--- Could not get {url}: {e} ---\n\n"


def summarize_text(text, query, model):
    """Summarizes text using an AI model."""
    summarization_prompt = f"Based on the following web content, please provide a comprehensive answer to the user's query: '{query}'. Synthesize the information from the sources into a single, coherent response. Do not just list the content from each source. Your answer should be well-structured, easy to understand, and directly address the user's question. Format the response using Markdown for readability.\n\n--- WEB CONTENT ---\n{text}"
    try:
        from .ai_service import call_chat_stream
        content = ""
        for chunk in call_chat_stream(model, [{"role": "user", "content": summarization_prompt}], "You are a helpful assistant."):
            content += chunk
        return content
    except Exception as e:
        raise ConnectionError(
            f"Could not connect to the AI model to summarize: {e}"
        ) from e


def web_search(query, conversation_id=None, user_id=None, user=None):
    """
    Performs a web search using the Google Search API, scrapes the top
    results, and uses an AI model to summarize the answer.
    """
    api_key = current_app.config.get("GOOGLE_API_KEY")
    cse_id = current_app.config.get("GOOGLE_CSE_ID")

    if not api_key or not cse_id:
        return "Error: Google Search API key or CSE ID is not configured."

    if not all([requests, BeautifulSoup]) or not _google_client_available():
        missing = [
            lib
            for lib, present in [
                ("'requests'", requests),
                ("'beautifulsoup4'", BeautifulSoup),
                ("'google-api-python-client'", _google_client_available()),
            ]
            if not present
        ]
        return (
            f"Error: Missing required libraries: {', '.join(missing)}.\n"
            "Recovery: install missing packages or use non-web-search tools."
        )

    try:
        search_results = google_search(api_key, cse_id, query)
        if not search_results:
            return f"No results found for '{query}'."

        consolidated_content = ""
        for result in search_results:
            consolidated_content += scrape_text_from_url(result["link"])

        if not consolidated_content.strip():
            return "Could not retrieve any content from the search results."

        max_length = 8000
        if len(consolidated_content) > max_length:
            consolidated_content = consolidated_content[:max_length] + "..."

        current_model = user.selected_model if user else "default_model_name"

        summary = summarize_text(
            consolidated_content, query, current_model
        )
        return f"Based on my web search, here is the answer to your query about '{query}':\n\n{summary}"

    except ConnectionError as e:
        return f"Error during web search: {e}"
    except Exception as e:
        return f"An unexpected error occurred during web search: {e}"
