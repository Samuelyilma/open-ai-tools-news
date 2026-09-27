"""Configuration for the Open Tool Drop collector.

Reads from environment variables (optional) and from watchlist.json.
No API keys are hard-coded.
"""

import os
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent

# ── GitHub token (optional — enables higher API rate limits) ──────
# Set GITHUB_TOKEN env var or place in .env (not committed).
GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN", "")

GITHUB_API_BASE = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "open-tool-drop-collector/1.0",
}
if GITHUB_TOKEN:
    GITHUB_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# For non-authenticated calls (public data only):
GITHUB_HEADERS_PUBLIC = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "open-tool-drop-collector/1.0",
}

# ── API rate-limit safety ──────────────────────────────────────────
# Wait this many seconds between GitHub API calls to be polite.
GITHUB_CALL_DELAY_SEC = 1.0

# ── Source config ──────────────────────────────────────────────────

# Minimum stars for a GitHub repo to be considered newsworthy (not from watchlist).
MIN_STARS_DEFAULT = 100

# Maximum number of items to collect per source per run.
MAX_ITEMS_PER_SOURCE = 8

# Only consider releases/items newer than this many days.
MAX_AGE_DAYS = 14

# ── Relevance keywords (for filtering search results) ─────────────
RELEVANCE_KEYWORDS = [
    "open source", "open-source", "ai", "agent", "llm", "local",
    "ollama", "langchain", "llama", "huggingface", "assistant",
    "automation", "self-hosted", "privacy", "cli", "developer tool",
    "android", "f-droid", "linux", "windows", "rust", "python",
    "typescript", "react", "node.js", "go", "webassembly",
    "MCP", "tool-calling", "inference", "model release",
]

# Keywords that indicate low-quality / irrelevant content:
REJECT_KEYWORDS = [
    "seo", "click here", "buy now", "download now",
    "affiliate", "sponsored", "advertisement",
]

# ── Watchlist ──────────────────────────────────────────────────────
# watchlist.json contains repos/projects to always monitor.
# Format: [{"repo": "owner/repo", "name": "...", "category": "...", "priority": 3}, ...]

WATCHLIST_PATH = PROJECT / "watchlist.json"


def load_watchlist() -> list[dict]:
    """Load watchlist from watchlist.json."""
    if not WATCHLIST_PATH.exists():
        return []
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_watchlist(wl: list[dict]) -> None:
    """Persist watchlist to watchlist.json."""
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(wl, f, indent=2, ensure_ascii=False)


# ── Gemini enrichment (optional) ───────────────────────────────────
# Only used if GEMINI_API_KEY env var is set. Does not block collection.

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_ENABLED = bool(GEMINI_API_KEY)

if GEMINI_ENABLED:
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    GEMINI_HEADERS = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GEMINI_API_KEY}",
    }
else:
    GEMINI_API_URL = ""
    GEMINI_HEADERS = {}
