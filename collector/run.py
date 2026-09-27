#!/usr/bin/env python3
"""Open Tool Drop — news collector runner.

Usage:
  python -m collector.run collect       # run all sources, filter, publish
  python -m collector.run collect-pull  # collect + git pull + git push + status
  python -m collector.run review       # show pending items for manual review
  python -m collector.run status       # show current news.json stats
  python -m collector.run watchlist    # show current watchlist
  python -m collector.run watch-add    <repo>           # add repo to watchlist
  python -m collector.run watch-remove <repo>           # remove repo from watchlist

Environment:
  GITHUB_TOKEN   — optional GitHub PAT for higher API rate limits
  GEMINI_API_KEY — optional, enables Gemini description enrichment

Data files (in project root):
  watchlist.json — repos to prioritize
  seen.json      — deduplication database
  news.json      — published items (consumed by index.html at runtime)
"""

import argparse
import subprocess
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from collector import config
from collector.sources import collect_releases_for_watchlist, collect_search, collect_hn
from collector.storage import load_news, load_seen, load_watchlist, save_watchlist, append_items, mark_seen
from collector.filter import run_quality_gate, _seen_key
from collector.enrich import enrich_items
from collector.models import Item


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def cmd_collect():
    """Run all sources, filter, enrich, publish."""
    print("=" * 60)
    print(f"  Open Tool Drop — collector run {_today_iso()}")
    print("=" * 60)

    items: list[Item] = []

    # ── 1. Watchlist releases (Tier 1) ───────────────────────────
    print("\n[1/4] Watchlist releases (Tier 1 — official GitHub releases)...")
    for item in collect_releases_for_watchlist():
        items.append(item)
    print(f"      → {len(items)} releases from watchlist")

    # ── 2. GitHub search (Tier 2) ────────────────────────────────
    print("\n[2/4] GitHub search (Tier 2 — public discovery)...")
    github_count = 0
    for item in collect_search():
        items.append(item)
        github_count += 1
    print(f"      → {github_count} repos from search")

    # ── 3. Hacker News (Tier 2) ──────────────────────────────────
    print("\n[3/4] Hacker News (Tier 2 — community feed)...")
    hn_count = 0
    for item in collect_hn():
        items.append(item)
        hn_count += 1
    print(f"      → {hn_count} stories from HN")

    if not items:
        print("\n⚠️  No items collected from any source. Nothing to do.")
        return

    # ── 4. Quality gate + dedup ──────────────────────────────────
    print("\n[4/4] Quality gate + duplicate detection...")
    publishable = run_quality_gate(iter(items))
    print(f"      → {len(publishable)} items passed to publish stage")

    # ── 5. Enrichment (optional) ─────────────────────────────────
    dicts = [item_to_site_dict(item) for item in publishable]
    dicts = enrich_items(dicts)

    # Rebuild Item list from enriched dicts for storage
    enriched_items = [Item(**{k: v for k, v in d.items() if k in Item.__dataclass_fields__})
                      for d in dicts]

    # Mark as seen
    for item in enriched_items:
        mark_seen(item)

    # ── 6. Publish ───────────────────────────────────────────────
    print("\n  Publishing to news.json...")
    total = append_items(enriched_items)
    print(f"      → news.json now holds {len(total)} published items")

    # Print summary
    print("\n  --- New items published ---")
    for it in enriched_items[:8]:
        tag = it.tag
        print(f"    [{tag.upper():7}] {it.tool[:50]:52} ({it.source_name})")
    if len(enriched_items) > 8:
        print(f"    ... and {len(enriched_items) - 8} more")

    print("\n  Done.")


def item_to_site_dict(item: Item) -> dict:
    """Mirror of storage.item_to_site_dict — avoid circular import."""
    return {
        "id": item.id, "tool": item.tool, "tag": item.tag,
        "icon": item.icon, "iconUrl": item.iconUrl,
        "desc": item.desc, "media": item.media, "links": item.links,
        "date": item.date, "source": item.source,
        "_category": item.category, "_source_name": item.source_name,
        "_repo_url": item.repo_url, "_version": item.version,
        "_priority": item.priority, "_collected_at": item.collected_at,
    }


def cmd_collect_pull():
    """collect + git pull + git push + status."""
    print("Running collection + git sync...")
    cmd_collect()

    print("\n--- Git sync ---")
    cwd = PROJECT
    print("  git pull...")
    r = subprocess.run(["git", "pull", "origin", "main"], cwd=cwd,
                       capture_output=True, text=True)
    print(r.stdout[-300:] if r.stdout else "")
    if r.returncode != 0:
        print(f"  git pull failed: {r.stderr[-200:]}")

    print("  git add + commit + push...")
    r = subprocess.run(["git", "add", "news.json", "seen.json"], cwd=cwd,
                       capture_output=True, text=True)
    r = subprocess.run(
        ["git", "commit", "-m", f"collector: auto-collect {_today_iso()} ({len(load_news())} items)"],
        cwd=cwd, capture_output=True, text=True)
    if r.returncode == 0:
        print("  committed.")
        r = subprocess.run(["git", "push", "origin", "main"], cwd=cwd,
                           capture_output=True, text=True)
        if r.returncode == 0:
            print("  pushed to GitHub.")
        else:
            print(f"  push failed: {r.stderr[-200:]}")
    else:
        print(f"  nothing to commit or commit failed: {r.stderr[-200:]}")


def cmd_review():
    """Show items that would be collected but haven't been published yet."""
    print("Review mode — showing what the collector would publish...")
    items: list[Item] = []
    for src_name, gen in [
        ("watchlist", collect_releases_for_watchlist),
        ("github-search", collect_search),
        ("hacker-news", collect_hn),
    ]:
        for item in gen():
            items.append(item)

    if not items:
        print("  No items to review — all sources returned empty.")
        return

    print(f"\n  {len(items)} items collected (before quality gate):")
    for it in items:
        key = _seen_key(it)
        seen = load_seen()
        pub = load_news()
        status = "NEW" if key not in seen and not any(
            i.get("id") == it.id for i in pub) else "SEEN"
        print(f"    [{status}] [{it.tag:7}] {it.tool[:48]:50} ⭐{it.stars:4} "
              f"{it.source_name}")


def cmd_status():
    """Show current news.json stats."""
    news = load_news()
    print(f"  Published items in news.json: {len(news)}")
    if not news:
        print("  (empty — no news published yet)")
        return

    from collections import Counter
    tag_counts = Counter(d.get("tag", "app") for d in news)
    print("\n  By tag:")
    for tag, count in sorted(tag_counts.items()):
        print(f"    {tag:10} {count}")

    print("\n  Most recent 5:")
    for d in sorted(news, key=lambda x: x.get("date", ""), reverse=True)[:5]:
        print(f"    [{d.get('tag','?'):7}] {d.get('tool','')[:48]:50} "
              f"{d.get('date','')}  ({d.get('source','')})")

    seen = load_seen()
    print(f"\n  Seen database entries: {len(seen)}")


def cmd_watchlist():
    wl = load_watchlist()
    print(f"  Watchlist ({len(wl)} repos):")
    if not wl:
        print("    (empty — add repos with 'watch-add')")
        return
    for entry in wl:
        print(f"    - {entry.get('repo','?'):30}  "
              f"cat={entry.get('category','?'):12}  "
              f"pri={entry.get('priority',0)}  "
              f"stars={entry.get('stars',0)}")


def cmd_watch_add(repo: str):
    wl = load_watchlist()
    if any(e.get("repo", "").strip() == repo for e in wl):
        print(f"  {repo} is already in the watchlist.")
        return
    wl.append({"repo": repo, "category": "open_source", "priority": 3, "stars": 0})
    save_watchlist(wl)
    print(f"  Added {repo} to watchlist (priority=3, category=open_source).")
    print("  Run 'collector watchlist' to confirm.")


def cmd_watch_remove(repo: str):
    wl = load_watchlist()
    before = len(wl)
    wl = [e for e in wl if e.get("repo", "").strip() != repo]
    if len(wl) == before:
        print(f"  {repo} not found in watchlist.")
        return
    save_watchlist(wl)
    print(f"  Removed {repo} from watchlist.")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Open Tool Drop collector",
        prog="python -m collector.run",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("collect", help="Run all sources, filter, publish to news.json")
    sub.add_parser("collect-pull", help="collect + git pull + git commit + git push")
    sub.add_parser("review", help="Show items that would be collected (dry run)")
    sub.add_parser("status", help="Show current news.json stats")
    sub.add_parser("watchlist", help="Show current watchlist")

    wa = sub.add_parser("watch-add", help="Add a repo to the watchlist")
    wa.add_argument("repo", help="owner/repo")

    wr = sub.add_parser("watch-remove", help="Remove a repo from the watchlist")
    wr.add_argument("repo", help="owner/repo")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return

    dispatch = {
        "collect": cmd_collect,
        "collect-pull": cmd_collect_pull,
        "review": cmd_review,
        "status": cmd_status,
        "watchlist": cmd_watchlist,
        "watch-add": lambda: cmd_watch_add(args.repo),
        "watch-remove": lambda: cmd_watch_remove(args.repo),
    }
    dispatch[args.command]()


if __name__ == "__main__":
    main()
