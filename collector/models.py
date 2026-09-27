"""Data models for the Open Tool Drop collector."""

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


# ── Tag mapping (maps collector category → site tag) ──────────────
# Site supports: agent | app | model | update
# Collector produces richer categories; this maps to the closest site tag.

CATEGORY_TO_TAG: dict[str, str] = {
    "ai_agent":     "agent",
    "agent":        "agent",
    "local_ai":     "agent",
    "ai_model":     "model",
    "model":        "model",
    "android":      "app",
    "mobile":       "app",
    "application":  "app",
    "desktop_app":  "app",
    "open_source":  "app",
    "developer_tool":"app",
    "web_dev":      "app",
    "release":      "update",
    "update":       "update",
    "hermes":       "agent",
}

DEFAULT_TAG = "app"


@dataclass
class Item:
    """One news item — matches the site's ITEMS array format (subset + extras)."""

    id: str                           # unique slug, used as DOM id and dedup key
    tool: str                         # display name (maps to site's "tool")
    tag: str                          # site tag: agent | app | model | update
    icon: str = ""                    # emoji fallback
    iconUrl: str = ""                 # optional image URL
    desc: str = ""                    # description (maps to site's "desc")
    media: dict = field(default_factory=dict)  # {type: "image"|"video", url: "..."}
    links: list[dict] = field(default_factory=list)  # [{label, url, kind}]
    date: str = ""                    # ISO date YYYY-MM-DD
    source: str = ""                  # collector source note (site shows this as "source")

    # ── Collector extras (not rendered by site, stored for dedup/admin) ──
    category: str = ""                # rich category: ai_agent, android, etc.
    version: str = ""                 # release version if applicable
    repo_url: str = ""                # GitHub repo URL
    project_url: str = ""             # project homepage
    source_url: str = ""              # original source URL (release page, HN post, etc.)
    source_name: str = ""             # human name of source: "GitHub", "Hacker News", etc.
    stars: int = 0                    # GitHub stars (for relevance scoring)
    priority: int = 0                 # 1=low, 2=medium, 3=high
    status: str = "published"         # published | pending | rejected
    collected_at: str = ""            # ISO datetime when collected


def item_to_site_dict(item: Item) -> dict:
    """Convert Item → dict format that the site's ITEMS array expects."""
    return {
        "id":          item.id,
        "tool":        item.tool,
        "tag":         item.tag,
        "icon":        item.icon,
        "iconUrl":     item.iconUrl,
        "desc":        item.desc,
        "media":       item.media,
        "links":       item.links,
        "date":        item.date,
        "source":      item.source or item.source_name or "",
    }


def item_from_site_dict(d: dict) -> Item:
    """Reconstruct Item from a dict that came from the site's ITEMS format."""
    return Item(
        id=d.get("id", ""),
        tool=d.get("tool", ""),
        tag=d.get("tag", "app"),
        icon=d.get("icon", ""),
        iconUrl=d.get("iconUrl", ""),
        desc=d.get("desc", ""),
        media=d.get("media", {}) or {},
        links=d.get("links", []) or [],
        date=d.get("date", ""),
        source=d.get("source", ""),
    )
