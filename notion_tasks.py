"""Notion read/write layer for the deep research worker."""

import re
import time
from typing import Optional

from notion_client import Client

from config import (
    require_notion_api_key,
    require_notion_task_database_id,
)

# Notion API limits.
TEXT_LIMIT = 2000            # max characters per rich_text item
RICH_TEXT_ITEM_LIMIT = 100   # max rich_text items per block
CHILDREN_LIMIT = 100         # max child blocks per append request

_notion_client: Optional[Client] = None


def get_notion_client() -> Client:
    """Return a cached Notion client built from the configured API key."""
    global _notion_client

    if _notion_client is None:
        _notion_client = Client(auth=require_notion_api_key())

    return _notion_client


def run_with_retry(func, max_attempts: int = 3, delay_seconds: int = 3):
    """Run a Notion API operation with simple retry."""
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as e:
            last_error = e
            print(f"Notion API attempt {attempt} failed: {e}")

            if attempt < max_attempts:
                time.sleep(delay_seconds)

    raise last_error


# ---------------------------------------------------------------------------
# Reading Notion properties
# ---------------------------------------------------------------------------


def get_text_property(page: dict, property_name: str) -> str:
    """Read plain text from a Notion title or rich_text property."""
    prop = page["properties"].get(property_name)

    if not prop:
        return ""

    prop_type = prop.get("type")

    if prop_type == "title":
        return "".join(item["plain_text"] for item in prop["title"])

    if prop_type == "rich_text":
        return "".join(item["plain_text"] for item in prop["rich_text"])

    return ""


def get_select_property(page: dict, property_name: str) -> str:
    """Read the selected option name from a Notion select property."""
    prop = page["properties"].get(property_name)

    if not prop:
        return ""

    if prop.get("type") != "select":
        return ""

    select_value = prop.get("select")

    if not select_value:
        return ""

    return select_value.get("name", "")


def get_status_property(page: dict, property_name: str) -> str:
    """Read the selected status name from a Notion status property."""
    prop = page["properties"].get(property_name)

    if not prop:
        return ""

    if prop.get("type") != "status":
        return ""

    status_value = prop.get("status")

    if not status_value:
        return ""

    return status_value.get("name", "")


def get_multi_select_property(page: dict, property_name: str) -> list[str]:
    """Read selected option names from a Notion multi_select property."""
    prop = page["properties"].get(property_name)

    if not prop:
        return []

    if prop.get("type") != "multi_select":
        return []

    return [
        item.get("name", "")
        for item in prop.get("multi_select", [])
        if item.get("name")
    ]


def get_url_property(page: dict, property_name: str) -> str:
    """Read a URL from a Notion url property."""
    prop = page["properties"].get(property_name)

    if not prop:
        return ""

    if prop.get("type") != "url":
        return ""

    return prop.get("url") or ""


def get_todo_task() -> Optional[dict]:
    """Get the oldest Notion task whose Status is Todo."""
    notion = get_notion_client()

    data_source_id = require_notion_task_database_id()

    response = notion.data_sources.query(
        data_source_id=data_source_id,
        filter={
            "property": "Status",
            "status": {
                "equals": "Todo",
            },
        },
        sorts=[
            {
                "timestamp": "created_time",
                "direction": "ascending",
            }
        ],
        page_size=1,
    )

    results = response.get("results", [])

    if not results:
        return None

    page = results[0]

    return {
        "page_id": page["id"],
        "question": get_text_property(page, "Question"),
        "priority": get_select_property(page, "Priority"),
        "topics": get_multi_select_property(page, "Topic"),
        "difficulty": get_select_property(page, "Difficulty"),
        "source_url": get_url_property(page, "Source URL"),
        "output_language": get_select_property(page, "Output Language"),
    }


# ---------------------------------------------------------------------------
# Writing Notion properties
# ---------------------------------------------------------------------------


def update_task_status(
    page_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """Update a Notion task's Status and optional Error Message."""
    notion = get_notion_client()

    properties: dict = {
        "Status": {
            "status": {
                "name": status,
            }
        }
    }

    if error_message:
        properties["Error Message"] = {
            "rich_text": plain_rich_text(error_message)
        }

    run_with_retry(
        lambda: notion.pages.update(
            page_id=page_id,
            properties=properties,
        )
    )


def update_result_summary(page_id: str, summary: str) -> None:
    """Update the Result Summary property of a Notion task."""
    notion = get_notion_client()

    run_with_retry(
        lambda: notion.pages.update(
            page_id=page_id,
            properties={
                "Result Summary": {
                    "rich_text": plain_rich_text(summary)
                }
            },
        )
    )


def update_resource_urls(page_id: str, urls: list[str]) -> None:
    """Update Resource URL and Resource URLs properties in Notion.

    Resource URL: URL property, stores the first URL only.
    Resource URLs: rich_text property, stores multiple URLs as text.
    """
    notion = get_notion_client()

    clean_urls = []

    for url in urls:
        if url and url.startswith(("http://", "https://")) and url not in clean_urls:
            clean_urls.append(url)

    if not clean_urls:
        return

    primary_url = clean_urls[0]
    urls_text = "\n".join(clean_urls)

    # Update single primary URL if the database has a "Resource URL" property.
    try:
        run_with_retry(
            lambda: notion.pages.update(
                page_id=page_id,
                properties={
                    "Resource URL": {
                        "url": primary_url
                    }
                },
            )
        )
    except Exception as e:
        print(f"Could not update Resource URL property: {e}")

    # Update multiple URLs if the database has a "Resource URLs" text property.
    try:
        run_with_retry(
            lambda: notion.pages.update(
                page_id=page_id,
                properties={
                    "Resource URLs": {
                        "rich_text": plain_rich_text(urls_text)
                    }
                },
            )
        )
    except Exception as e:
        print(f"Could not update Resource URLs property: {e}")


def update_task_topics(page_id: str, topics: list[str]) -> None:
    """Update the Topic multi-select property of a Notion task."""
    notion = get_notion_client()

    topic_values = [{"name": topic} for topic in topics]

    run_with_retry(
        lambda: notion.pages.update(
            page_id=page_id,
            properties={
                "Topic": {
                    "multi_select": topic_values
                }
            },
        )
    )


# ---------------------------------------------------------------------------
# Markdown -> Notion blocks
# ---------------------------------------------------------------------------

# Matches inline code, links, bold and italic. Code is matched first so its
# contents are never re-parsed as bold or italic.
_INLINE_PATTERN = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<link>\[(?P<link_text>[^\]]*)\]\((?P<link_url>[^)\s]+)\))"
    r"|(?P<bold>\*\*(?P<bold_text>.+?)\*\*)"
    r"|(?P<italic>(?<![\w*])\*(?P<italic_text>[^*\n]+)\*(?!\*))"
)

# Notion accepts a fixed set of code languages; map the common aliases.
_CODE_LANGUAGES = {
    "": "plain text",
    "text": "plain text",
    "txt": "plain text",
    "py": "python",
    "python": "python",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "sh": "shell",
    "bash": "shell",
    "zsh": "shell",
    "shell": "shell",
    "console": "shell",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "toml": "toml",
    "sql": "sql",
    "html": "html",
    "css": "css",
    "md": "markdown",
    "markdown": "markdown",
    "c": "c",
    "cpp": "c++",
    "c++": "c++",
    "java": "java",
    "go": "go",
    "rust": "rust",
    "r": "r",
}


def _chunk_text(text: str, size: int = TEXT_LIMIT) -> list[str]:
    """Split text into pieces Notion accepts, instead of truncating it."""
    if not text:
        return [""]

    return [text[i:i + size] for i in range(0, len(text), size)]


def _text_items(
    content: str,
    annotations: dict | None = None,
    url: str | None = None,
) -> list[dict]:
    """Build rich_text items for a single styled run of text."""
    items = []

    for piece in _chunk_text(content):
        item: dict = {
            "type": "text",
            "text": {"content": piece},
        }

        if url:
            item["text"]["link"] = {"url": url}

        if annotations:
            item["annotations"] = dict(annotations)

        items.append(item)

    return items


def plain_rich_text(text: str) -> list[dict]:
    """Build an unstyled rich_text array, chunked to Notion's limits."""
    return _text_items(text)[:RICH_TEXT_ITEM_LIMIT]


def parse_inline_markdown(text: str) -> list[dict]:
    """Convert inline Markdown (bold, italic, code, links) to rich_text."""
    items: list[dict] = []
    position = 0

    for match in _INLINE_PATTERN.finditer(text):
        if match.start() > position:
            items.extend(_text_items(text[position:match.start()]))

        if match.group("code"):
            items.extend(
                _text_items(
                    match.group("code").strip("`"),
                    annotations={"code": True},
                )
            )
        elif match.group("link"):
            items.extend(
                _text_items(
                    match.group("link_text") or match.group("link_url"),
                    url=match.group("link_url"),
                )
            )
        elif match.group("bold"):
            items.extend(
                _text_items(
                    match.group("bold_text"),
                    annotations={"bold": True},
                )
            )
        else:
            items.extend(
                _text_items(
                    match.group("italic_text"),
                    annotations={"italic": True},
                )
            )

        position = match.end()

    if position < len(text):
        items.extend(_text_items(text[position:]))

    if not items:
        items = _text_items(text)

    return items[:RICH_TEXT_ITEM_LIMIT]


def _text_block(block_type: str, text: str) -> dict:
    """Build a simple text-bearing Notion block."""
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": parse_inline_markdown(text)
        },
    }


def _code_block(code: str, language: str) -> dict:
    """Build a Notion code block, chunking the body to the text limit."""
    return {
        "object": "block",
        "type": "code",
        "code": {
            "language": _CODE_LANGUAGES.get(
                language.strip().lower(),
                "plain text",
            ),
            "rich_text": _text_items(code)[:RICH_TEXT_ITEM_LIMIT],
        },
    }


def _split_table_row(line: str) -> list[str]:
    """Split a Markdown table row into its cell texts."""
    stripped = line.strip()

    if stripped.startswith("|"):
        stripped = stripped[1:]

    if stripped.endswith("|"):
        stripped = stripped[:-1]

    return [cell.strip() for cell in stripped.split("|")]


def _is_table_separator(line: str) -> bool:
    """Return True for a Markdown table separator row such as |---|:--:|."""
    stripped = line.strip()

    if not stripped.startswith("|") or "-" not in stripped:
        return False

    cells = [cell for cell in _split_table_row(stripped) if cell]

    if not cells:
        return False

    return all(re.fullmatch(r":?-+:?", cell) is not None for cell in cells)


def _table_block(header: list[str], rows: list[list[str]]) -> dict:
    """Build a real Notion table block from Markdown header and body rows."""
    width = max(1, min(len(header), 100))

    def make_row(cells: list[str]) -> dict:
        padded = (cells + [""] * width)[:width]

        return {
            "object": "block",
            "type": "table_row",
            "table_row": {
                "cells": [parse_inline_markdown(cell) for cell in padded]
            },
        }

    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": True,
            "has_row_header": False,
            "children": [make_row(header)] + [make_row(row) for row in rows],
        },
    }


def markdown_to_notion_blocks(markdown_text: str) -> list[dict]:
    """Convert Markdown text into Notion blocks.

    Supports headings 1-3, bulleted and numbered lists, fenced code blocks,
    block quotes, dividers, tables, and inline bold/italic/code/links.
    Long text is chunked rather than truncated.
    """
    blocks: list[dict] = []
    lines = markdown_text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Blank line
        if not line:
            i += 1
            continue

        # Fenced code block
        if line.startswith("```"):
            language = line[3:].strip()
            i += 1
            code_lines = []

            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1

            i += 1  # skip the closing fence
            blocks.append(_code_block("\n".join(code_lines), language))
            continue

        # Table: a pipe row followed by a separator row
        if (
            line.startswith("|")
            and i + 1 < len(lines)
            and _is_table_separator(lines[i + 1])
        ):
            header = _split_table_row(line)
            i += 2
            rows = []

            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_table_row(lines[i]))
                i += 1

            blocks.append(_table_block(header, rows))
            continue

        # Divider
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", line):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # Headings. Notion has no heading_4, so #### folds into heading_3.
        if line.startswith("#### "):
            blocks.append(_text_block("heading_3", line[5:]))
        elif line.startswith("### "):
            blocks.append(_text_block("heading_3", line[4:]))
        elif line.startswith("## "):
            blocks.append(_text_block("heading_2", line[3:]))
        elif line.startswith("# "):
            blocks.append(_text_block("heading_1", line[2:]))

        # Block quote
        elif line.startswith("> "):
            blocks.append(_text_block("quote", line[2:]))

        # Bulleted list
        elif re.match(r"^[-*+]\s+", line):
            blocks.append(
                _text_block("bulleted_list_item", re.sub(r"^[-*+]\s+", "", line))
            )

        # Numbered list
        elif re.match(r"^\d+[.)]\s+", line):
            blocks.append(
                _text_block("numbered_list_item", re.sub(r"^\d+[.)]\s+", "", line))
            )

        # Paragraph
        else:
            blocks.append(_text_block("paragraph", line))

        i += 1

    return blocks


def append_markdown_to_page(page_id: str, markdown_text: str) -> int:
    """Append Markdown content to a Notion page body.

    Returns the number of top-level blocks written.
    """
    notion = get_notion_client()

    children = markdown_to_notion_blocks(markdown_text)

    if not children:
        return 0

    for i in range(0, len(children), CHILDREN_LIMIT):
        batch = children[i:i + CHILDREN_LIMIT]

        run_with_retry(
            lambda batch=batch: notion.blocks.children.append(
                block_id=page_id,
                children=batch,
            )
        )

    return len(children)


def append_result_to_task_page(page_id: str, result: str) -> None:
    """Append the final research result to the Notion task page body."""
    append_markdown_to_page(page_id, result)
