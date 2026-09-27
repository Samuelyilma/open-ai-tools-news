"""Filtering, quality gate, and duplicate detection for collected items."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Iterator
from pathlib import Path

from collector.models import Item, item_to_site_dict

PROJECT = Path(__file__).resolve().parent.parent
SEEN_PATH = PROJECT / "seen.json"
NEWS_PATH = PROJECT / "news.json"


def _load_seen() -> dict:
    if not SEEN_PATH.exists():
        return {}
    try:
        with open(SEEN_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_seen(seen: dict) -> None:
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def _seen_key(item: Item) -> str:
    """Stable unique key for duplicate detection.

    Priority: source_url > (source_name + repo_url + version) > hash(title+date)
    """
    if item.source_url:
        return f"url:{item.source_url}"
    if item.repo_url or item.version:
        parts = [item.source_name or "unknown"]
        if item.repo_url:
            parts.append(item.repo_url)
        if item.version:
            parts.append(item.version)
        return f"release:{'|||'.join(parts)}"
    # Fallback: hash of tool+date+source
    raw = f"{item.tool}|{item.date}|{item.source_name}|{item.repo_url}"
    return f"hash:{hashlib.md5(raw.encode()).hexdigest()[:12]}"


def _seen_value(item: Item) -> dict:
    """Store enough to detect future duplicates and for admin review."""
    return {
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


def _load_news() -> list[dict]:
    if not NEWS_PATH.exists():
        return []
    try:
        with open(NEWS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_news(items: list[dict]) -> None:
    with open(NEWS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def _is_duplicate(item: Item, seen: dict, existing: list[dict]) -> bool:
    """Return True if this item is a duplicate of something we already have."""
    key = _seen_key(item)

    # Check against previously seen items
    if key in seen:
        prev = seen[key]
        # URL match is exact duplicate
        if item.source_url and prev.get("source_url") == item.source_url:
            return True
        # Same repo+version is a re-release (skip)
        if item.repo_url and prev.get("repo_url") == item.repo_url and \
           item.version and prev.get("version") == item.version:
            return True
        # Same source_url means it's the same announcement
        if prev.get("source_url") == item.source_url:
            return True

    # Check against currently published news (news.json)
    for pub in existing:
        pub_url = pub.get("source_url") or ""
        item_url = item.source_url or ""
        if pub_url and item_url and pub_url == item_url:
            return True
        pub_repo = pub.get("repo_url") or ""
        if item.repo_url and pub_repo == item.repo_url and item.version and pub.get("version") == item.version:
            return True
        # Title similarity
        if pub.get("tool", "").lower() == item.tool.lower() and \
           pub.get("date") == item.date:
            # Same tool on same day from possibly different source — likely the same news
            if item.source_url and pub.get("source_url"):
                return True

    return False


def _quality_score(item: Item) -> int:
    """Higher = more newsworthy. Used to rank items.

    - Watchlist priority boost
    - Stars / engagement
    - Category priority
    """
    score = 0
    # Base on priority
    score += item.priority * 10
    # Stars/engagement
    score += min(item.stars, 500)
    # Category bonuses
    if item.category in ("ai_agent", "hermes"):
        score += 30
    if item.category == "android":
        score += 15
    # Watchlist repos always score high
    if item.priority >= 3:
        score += 50
    return score


def run_quality_gate(items: Iterator[Item]) -> list[Item]:
    """Apply quality gate and duplicate detection. Return publishable Items."""
    seen = _load_seen()
    existing = _load_news()
    result: list[Item] = []
    rejected = 0

    for item in items:
        # Quality gate: reject low-score items unless watchlist
        if item.priority < 2 and item.stars < 20 and \
           item.category not in ("ai_agent", "hermes"):
            rejected += 1
            continue

        if _is_duplicate(item, seen, existing):
            rejected += 1
            continue

        # Update seen database
        seen[_seen_key(item)] = _seen_value(item)
        result.append(item)

    # Persist seen database
    _save_seen(seen)

    print(f"  [filter] {len(result)} passed quality gate, {rejected} rejected (dup/low-quality)")

    # Sort by quality score descending, then by collected_at
    result.sort(key=lambda i: (_quality_score(i), i.collected_at or ""), reverse=True)
    return result


def publish_items(items: list[Item]) -> list[dict]:
    """Convert Items to site dicts, merge with existing published news, save.

    Keeps only the most recent MAX_PUBLISHED items in news.json.
    Existing published items are preserved (they don't get re-filtered).
    """
    MAX_PUBLISHED = 40
    existing = _load_news()
    existing_ids = {e.get("id", "") for e in existing}

    new_dicts = [item_to_site_dict(i) for i in items if i.id not in existing_ids]
    merged = existing + new_dicts
    # Deduplicate by id (keep first occurrence = oldest)
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for d in merged:
        did = d.get("id", "")
        if did not in seen_ids:
            seen_ids.add(did)
            deduped.append(d)

    # Keep only the most recent MAX_PUBLISHED
    if len(deduped) > MAX_PUBLISHED:
        # Sort by date descending, keep newest
        deduped.sort(key=lambda d: d.get("date", ""), reverse=True)
        deduped = deduped[:MAX_PUBLISHED]
        # Re-sort by date descending for final output
        deduped.sort(key=lambda d: d.get("date", ""), reverse=True)

    _save_news(deduped)
    print(f"  [storage] news.json now has {len(deduped)} published items")
    return deduped
