"""Tools exposed to the deep research agent."""

import httpx
from langchain.tools import tool
from markdownify import markdownify
from tavily import TavilyClient

from config import (
    NOTION_PARENT_PAGE_ID,
    TAVILY_API_KEY,
    require_notion_api_key,
)

# Cached clients. Built on first use so importing this module never performs
# network setup or fails on missing optional configuration.
_tavily_client: TavilyClient | None = None


def get_tavily_client() -> TavilyClient:
    """Return a cached Tavily client."""
    global _tavily_client

    if _tavily_client is None:
        _tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

    return _tavily_client


@tool(parse_docstring=True)
def tavily_search(query: str, max_results: int = 3) -> str:
    """Search the web using Tavily.

    Args:
        query: The search question or keyword.
        max_results: Maximum number of search results.

    Returns:
        Search results containing titles, URLs, and webpage content.
    """
    try:
        response = get_tavily_client().search(
            query=query,
            max_results=max_results,
        )
    except Exception as e:
        return f"Error: Tavily search for '{query}' failed. Reason: {e!s}"

    results = response.get("results", [])

    if not results:
        return f"No search results found for '{query}'."

    # Render as readable text so the model reliably sees titles and URLs,
    # instead of str() of a raw dict.
    parts = []

    for i, item in enumerate(results, start=1):
        parts.append(
            f"[{i}] {item.get('title', 'Untitled')}\n"
            f"URL: {item.get('url', '')}\n"
            f"{item.get('content', '').strip()}"
        )

    return "\n\n".join(parts)


@tool(parse_docstring=True)
def fetch_webpage_content(url: str) -> str:
    """Fetch a webpage and convert its HTML content to Markdown.

    Args:
        url: The webpage URL to fetch.

    Returns:
        Webpage content converted to Markdown text.
    """
    try:
        response = httpx.get(url, timeout=20, follow_redirects=True)
        response.raise_for_status()
    except Exception as e:
        return (
            f"Error: failed to fetch webpage '{url}'. "
            f"Reason: {e!s}."
        )

    try:
        markdown_text = markdownify(response.text)
    except Exception as e:
        return (
            f"Error: failed to convert webpage '{url}' to Markdown. "
            f"Reason: {e!s}."
        )

    return f"Source URL: {url}\n\n{markdown_text[:12000]}"


@tool(parse_docstring=True)
def save_note_to_notion(title: str, content: str) -> str:
    """Save a research note to a new Notion page.

    Args:
        title: Title of the Notion page to create.
        content: Markdown-style note content to save.

    Returns:
        Confirmation message with the created Notion page id.
    """
    # Imported here to keep this module importable without Notion configured.
    from notion_client import Client

    from notion_tasks import append_markdown_to_page

    if not NOTION_PARENT_PAGE_ID:
        return "Error: NOTION_PARENT_PAGE_ID is not set."

    try:
        notion_api_key = require_notion_api_key()
    except RuntimeError as e:
        return f"Error: {e!s}"

    notion = Client(auth=notion_api_key)

    try:
        page = notion.pages.create(
            parent={"page_id": NOTION_PARENT_PAGE_ID},
            properties={
                "title": {
                    "title": [
                        {
                            "type": "text",
                            "text": {"content": title[:100]},
                        }
                    ]
                }
            },
        )
    except Exception as e:
        return f"Error: failed to create Notion page. Reason: {e!s}"

    try:
        # Append in batches so long notes are not silently truncated.
        append_markdown_to_page(page["id"], content)
    except Exception as e:
        return (
            f"Error: created Notion page {page['id']} but failed to write "
            f"its content. Reason: {e!s}"
        )

    return f"Saved note to Notion successfully. Page id: {page['id']}"
