"""Open-source news sources — GitHub Releases, GitHub Search, Hacker News.

Tier 1 (official/high-trust):
  - collect_releases_for_watchlist(): releases from watched repos (GitHub API)

Tier 2 (public discovery):
  - collect_search(): GitHub search API for new open-source projects
  - collect_hn(): Hacker News new stories (public Firebase API, no auth)
"""

import time
import re
import hashlib
from datetime import date, datetime, timezone
from typing import Generator
import requests

from collector.models import Item, CATEGORY_TO_TAG, DEFAULT_TAG
from collector import config


def _today_iso() -> str:
    return date.today().isoformat()


def _slug(text: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    return re.sub(r"^-|-$", "", t) or "item"


# ─────────────────────────────────────────────────────────────────────
# TIER 1 — WATCHLIST RELEASES (GitHub Releases API)
# ─────────────────────────────────────────────────────────────────────

def collect_releases_for_watchlist() -> Generator[Item, None, None]:
    """Fetch recent releases from each watched repo.

    Tier 1 source. Each release comes from the project's official GitHub repo.
    """
    wl = config.load_watchlist()
    if not wl:
        return

    for entry in wl:
        repo = entry.get("repo", "").strip()
        if not repo or "/" not in repo:
            continue

        priority = int(entry.get("priority", 0) or 0)
        category = entry.get("category", "open_source") or "open_source"
        name_override = entry.get("name", "").strip() or None

        print(f"  [watchlist] {repo} (priority={priority})")

        url = f"{config.GITHUB_API_BASE}/repos/{repo}/releases?per_page=10"
        headers = config.GITHUB_HEADERS if config.GITHUB_TOKEN else config.GITHUB_HEADERS_PUBLIC
        data = _fetch_json(url, headers)
        if not data:
            continue
        time.sleep(config.GITHUB_CALL_DELAY_SEC)

        for rel in data:
            tag = rel.get("tag_name", "")
            name = rel.get("name", tag) or tag
            published_at = rel.get("published_at", "") or ""

            # Skip old releases
            if not _is_recent_iso(published_at, config.MAX_AGE_DAYS):
                continue

            body = (rel.get("body") or "").strip()
            desc = body if len(body) <= 600 else body[:597] + "..."
            if not desc:
                desc = f"Release {tag} of {name}."

            # Pick a preview image from release assets
            media = {}
            for a in rel.get("assets", []) or []:
                au = (a.get("url") or "").lower()
                if au.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    media = {"type": "image", "url": a.get("url")}
                    break

            repo_url = f"https://github.com/{repo}"
            links = []
            rel_page = rel.get("html_url", "")
            if rel_page:
                links.append({"label": f"Release {tag}", "url": rel_page, "kind": "primary"})
            links.append({"label": "View on GitHub", "url": repo_url, "kind": "github"})
            project_url = entry.get("project_url", "").strip()
            if project_url and project_url != repo_url:
                links.append({"label": "Project site", "url": project_url, "kind": "secondary"})
            docs_url = entry.get("docs_url", "").strip()
            if docs_url:
                links.append({"label": "Docs", "url": docs_url, "kind": "secondary"})

            yield Item(
                id=f"github-release-{repo}-{tag.replace('.', '')}-{rel.get('id', 0)}",
                tool=name_override or name,
                tag=CATEGORY_TO_TAG.get(category, DEFAULT_TAG),
                icon=entry.get("icon", ""),
                iconUrl=entry.get("iconUrl", "") or "",
                desc=desc,
                media=media,
                links=links,
                date=published_at[:10] if published_at else _today_iso(),
                source=f"github.com/{repo}",
                category=category,
                version=tag,
                repo_url=repo_url,
                project_url=project_url,
                source_url=rel_page,
                source_name="GitHub",
                stars=entry.get("stars", 0) or 0,
                priority=priority,
            )


# ─────────────────────────────────────────────────────────────────────
# TIER 2 — GITHUB SEARCH (Search API)
# ─────────────────────────────────────────────────────────────────────

def collect_search() -> Generator[Item, None, None]:
    """Search GitHub for new/exciting open-source repos.

    Tier 2 discovery source. Uses the GitHub Search API.
    """
    headers = config.GITHUB_HEADERS if config.GITHUB_TOKEN else config.GITHUB_HEADERS_PUBLIC
    cutoff = _iso_days_ago(config.MAX_AGE_DAYS)

    queries = [
        f"topic:ai topic:agent topic:open-source pushed:>{cutoff}",
        f"language:python topic:ai topic:open-source stars:>=50 pushed:>{cutoff}",
        f"language:rust topic:open-source stars:>=50 pushed:>{cutoff}",
        f"topic:android topic:open-source stars:>={config.MIN_STARS_DEFAULT}",
        f"topic:MCP topic:open-source stars:>=20 pushed:>{cutoff}",
        f"topic:local-ai topic:open-source stars:>=50 pushed:>{cutoff}",
        f"topic:hermes-agent stars:>=10",
    ]

    seen_full_names: set[str] = set()
    count = 0

    for q in queries:
        if count >= config.MAX_ITEMS_PER_SOURCE * 2:
            break
        print(f"  [search] {q[:80]}...")
        url = f"{config.GITHUB_API_BASE}/search/repositories?q={requests.utils.quote(q)}&sort=updated&per_page=25"
        data = _fetch_json(url, headers)
        time.sleep(config.GITHUB_CALL_DELAY_SEC)
        if not data or "items" not in data:
            continue

        for repo in data["items"]:
            full_name = repo.get("full_name", "")
            if not full_name or full_name in seen_full_names:
                continue
            seen_full_names.add(full_name)

            stars = repo.get("stargazers_count", 0)
            if stars < 20:
                continue

            # Relevance filter
            desc = (repo.get("description") or "").lower()
            name = (repo.get("name") or "").lower()
            combined = f"{name} {desc}"
            if not any(kw.lower() in combined for kw in config.RELEVANCE_KEYWORDS):
                continue
            if any(rk.lower() in combined for rk in config.REJECT_KEYWORDS):
                continue

            updated_at = repo.get("updated_at", "") or ""
            if not _is_recent_iso(updated_at, 3):
                continue

            topic_list = [t.lower() for t in repo.get("topics", []) or []]
            topic_text = " ".join(topic_list)
            cat = "open_source"
            if any(k in topic_text for k in ["ai", "agent", "llm", "mcp"]):
                cat = "ai_agent"
            elif "android" in topic_text:
                cat = "android"
            elif "hermes" in topic_text or "hermes-agent" in full_name:
                cat = "hermes"

            site_tag = CATEGORY_TO_TAG.get(cat, DEFAULT_TAG)
            tool_name = repo.get("name", "").replace("-", " ").replace("_", " ").title()
            if not tool_name:
                tool_name = full_name.split("/")[-1].replace("-", " ").replace("_", " ").title()

            repo_url = repo.get("html_url", "")
            homepage = (repo.get("homepage") or "").strip()

            links = []
            if homepage and homepage != repo_url:
                links.append({"label": "Project site", "url": homepage, "kind": "primary"})
            links.append({"label": "View on GitHub", "url": repo_url, "kind": "github"})

            desc_full = repo.get("description") or "An open-source project."
            if len(desc_full) > 500:
                desc_full = desc_full[:497] + "..."

            yield Item(
                id=f"github-search-{full_name}-{_slug(q)[:8]}",
                tool=tool_name,
                tag=site_tag,
                icon="",
                iconUrl="",
                desc=desc_full,
                media={},
                links=links,
                date=_today_iso(),
                source=f"github.com/{full_name}",
                category=cat,
                version="",
                repo_url=repo_url,
                project_url=homepage,
                source_url=repo_url,
                source_name="GitHub",
                stars=stars,
                priority=2 if stars >= 100 else 1,
            )
            count += 1


# ─────────────────────────────────────────────────────────────────────
# TIER 2 — HACKER NEWS (public Firebase API, no auth)
# ─────────────────────────────────────────────────────────────────────

_HN_BASE = "https://hacker-news.firebaseio.com/v0"
_HEADERS = {"User-Agent": "open-tool-drop-collector/1.0"}

_HN_RELEVANCE = [
    "open source", "open-source", "github", "gitlab",
    "ai", "llm", "language model", "agent", "automation",
    "rust", "python", "typescript", "node", "linux",
    "android", "f-droid", "self-hosted", "privacy",
    "docker", "kubernetes", "devtool", "developer",
    "release", "launched", "announced", "new",
]
_HN_REJECT = ["job", "hiring", "career", "interview", "salary",
              "deal", "discount", "coupon", "sale", "offer"]


def collect_hn() -> Generator[Item, None, None]:
    """Poll HN new stories, filter for relevance, yield as Items."""
    print("  [HN] fetching new story IDs...")
    try:
        r = requests.get(f"{_HN_BASE}/newstories.json", headers=_HEADERS, timeout=20)
        r.raise_for_status()
        ids = r.json()
    except requests.RequestException as e:
        print(f"    [HN error] {e}")
        return
    if not isinstance(ids, list):
        print("    [HN warning] unexpected response")
        return

    print(f"  [HN] {len(ids)} new stories, scanning top 60...")
    count = 0
    for sid in ids[:60]:
        if count >= config.MAX_ITEMS_PER_SOURCE:
            break
        try:
            r2 = requests.get(f"{_HN_BASE}/item/{sid}.json", headers=_HEADERS, timeout=15)
            r2.raise_for_status()
            s = r2.json()
        except requests.RequestException:
            continue
        if not isinstance(s, dict) or s.get("type") != "story":
            continue

        title = s.get("title", "") or ""
        url = s.get("url") or ""
        hostname = s.get("hostname") or ""
        pts = s.get("score", 0) or 0
        descendants = s.get("descendants", 0) or 0

        if pts < 5:
            continue
        if not _hn_relevant(title, s.get("text", ""), hostname, url):
            continue

        cat = _hn_guess_category(title, s.get("text", ""), hostname)
        tag = CATEGORY_TO_TAG.get(cat, DEFAULT_TAG)

        domain = hostname or "news.ycombinator.com"
        if url and not url.startswith("https://news.ycombinator.com"):
            domain = re.sub(r"^https?://", "", url).split("/")[0]

        parts = [title]
        if domain and domain != title[:len(domain)]:
            parts.append(f"via {domain}")
        if pts > 5 or descendants > 0:
            parts.append(f"{pts} pts, {descendants} comments")
        desc = " — ".join(parts)

        media = {}
        if s.get("media") == "image" and url:
            media = {"type": "image", "url": url}

        links = []
        if url and url != f"https://news.ycombinator.com/item?id={sid}":
            kind = "github" if "github.com" in url.lower() else "primary"
            label = "View on GitHub" if "github.com" in url.lower() else "Read more"
            links.append({"label": label, "url": url, "kind": kind})
        links.append({
            "label": "HN discussion",
            "url": f"https://news.ycombinator.com/item?id={sid}",
            "kind": "secondary",
        })

        yield Item(
            id=f"hn-{sid}",
            tool=title[:120],
            tag=tag,
            icon="",
            iconUrl="",
            desc=desc,
            media=media,
            links=links,
            date=_today_iso(),
            source=f"hacker news ({domain})" if domain else "hacker news",
            category=cat,
            version="",
            repo_url="",
            project_url=url or "",
            source_url=f"https://news.ycombinator.com/item?id={sid}",
            source_name="Hacker News",
            stars=pts,
            priority=2 if pts >= 50 else 1,
        )
        count += 1
        time.sleep(0.3)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _fetch_json(url: str, headers: dict, timeout: int = 30):
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"    [API error] {e}")
        return None


def _is_recent_iso(date_str: str, days: int) -> bool:
    if not date_str:
        return True
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt >= cutoff.replace(tzinfo=None)
    except (ValueError, TypeError):
        return True


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")


def _hn_relevant(title: str, text: str, hostname: str, url: str) -> bool:
    blob = (title + " " + text + " " + hostname + " " + url).lower()
    if not any(k in blob for k in _HN_RELEVANCE):
        return False
    if any(r in blob for r in _HN_REJECT):
        return False
    return True


def _hn_guess_category(title: str, text: str, hostname: str) -> str:
    t = (title + " " + text).lower()
    if any(k in t for k in ["ai", "llm", "agent", "language model", "automation",
                              "huggingface", "openai", "mistral", "llama",
                              "stability ai", "anthropic"]):
        return "ai_agent"
    if any(k in t for k in ["android", "f-droid", "fdroid", "mobile app",
                              "ios app", "iphone", "ipad"]):
        return "android"
    if any(k in t for k in ["rust", "linux", "windows", "macos", "desktop app",
                              "self-hosted", "docker", "kubernetes"]):
        return "open_source"
    return "open_source"
