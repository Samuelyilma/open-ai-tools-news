"""Storage layer — read/write news.json, seen.json, watchlist.json."""

import json
from pathlib import Path

from collector.models import Item, item_to_site_dict

PROJECT = Path(__file__).resolve().parent.parent
NEWS_PATH = PROJECT / "news.json"
SEEN_PATH = PROJECT / "seen.json"
WATCHLIST_PATH = PROJECT / "watchlist.json"


# ── News ───────────────────────────────────────────────────────────

def load_news() -> list[dict]:
    """Load currently published news items from news.json."""
    if not NEWS_PATH.exists():
        return []
    try:
        with open(NEWS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_news(items: list[dict]) -> None:
    """Write the full news list to news.json."""
    with open(NEWS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def append_items(new_items: list[Item]) -> list[dict]:
    """Add new Items to news.json (without duplicates), return full list."""
    existing = load_news()
    existing_ids = {e.get("id", "") for e in existing}

    new_dicts = []
    for item in new_items:
        if item.id in existing_ids:
            continue
        d = item_to_site_dict(item)
        # Include collector extras for admin/debug (not rendered by site)
        d["_category"] = item.category
        d["_source_name"] = item.source_name
        d["_repo_url"] = item.repo_url
        d["_version"] = item.version
        d["_priority"] = item.priority
        d["_collected_at"] = item.collected_at
        new_dicts.append(d)

    # Merge: existing + new, dedup by id (keep first = oldest), cap at 50
    merged = existing + new_dicts
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for d in merged:
        did = d.get("id", "")
        if did not in seen_ids:
            seen_ids.add(did)
            deduped.append(d)

    # Keep newest 50
    if len(deduped) > 50:
        deduped.sort(key=lambda d: d.get("date", ""), reverse=True)
        deduped = deduped[:50]

    save_news(deduped)
    return deduped


# ── Seen (dedup database) ──────────────────────────────────────────

def load_seen() -> dict:
    """Load the seen-items database (key → metadata)."""
    if not SEEN_PATH.exists():
        return {}
    try:
        with open(SEEN_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_seen(seen: dict) -> None:
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def mark_seen(item: Item) -> None:
    seen = load_seen()
    key = _seen_key(item)
    seen[key] = {
        "id": item.id,
        "tool": item.tool,
        "date": item.date,
        "source_name": item.source_name,
        "source_url": item.source_url,
        "repo_url": item.repo_url,
        "version": item.version,
        "category": item.category,
        "priority": item.priority,
        "collected_at": item.collected_at,
    }
    save_seen(seen)


def _seen_key(item: Item) -> str:
    """Stable dedup key."""
    if item.source_url:
        return f"url:{item.source_url}"
    parts = [item.source_name or "unknown"]
    if item.repo_url:
        parts.append(item.repo_url)
    if item.version:
        parts.append(item.version)
    raw = "|".join(parts)
    return f"release:{raw}"


# ── Watchlist ──────────────────────────────────────────────────────

def load_watchlist() -> list[dict]:
    if not WATCHLIST_PATH.exists():
        return []
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_watchlist(wl: list[dict]) -> None:
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(wl, f, indent=2, ensure_ascii=False)
