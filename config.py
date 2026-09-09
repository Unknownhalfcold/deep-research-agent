import os

from dotenv import load_dotenv

load_dotenv()


def require_env(name: str) -> str:
    """Read a required environment variable, or raise a clear error."""
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )

    return value


# DeepSeek
DEEPSEEK_API_KEY = require_env(
    "DEEPSEEK_API_KEY"
)

DEEPSEEK_MODEL = os.getenv(
    "DEEPSEEK_MODEL",
    "deepseek-chat"
)

DEEPSEEK_BASE_URL = os.getenv(
    "DEEPSEEK_BASE_URL",
    "https://api.deepseek.com"
)


# Tavily
TAVILY_API_KEY = require_env(
    "TAVILY_API_KEY"
)


# Notion
#
# Notion is only needed by notion_worker.py / notion_tasks.py, so these are
# read lazily. Importing config.py (e.g. from main.py or deep_research.py)
# must not fail just because Notion is not configured yet.
NOTION_API_KEY = os.getenv("NOTION_API_KEY")

NOTION_TASK_DATABASE_ID = os.getenv("NOTION_TASK_DATABASE_ID")

NOTION_PARENT_PAGE_ID = os.getenv("NOTION_PARENT_PAGE_ID")


def require_notion_api_key() -> str:
    """Return the Notion API key, raising only when Notion is actually used."""
    return require_env("NOTION_API_KEY")


def require_notion_task_database_id() -> str:
    """Return the Notion task data source id, raising only when it is used."""
    return require_env("NOTION_TASK_DATABASE_ID")
