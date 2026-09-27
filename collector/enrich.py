"""Optional Gemini enrichment — adds titles/descriptions to raw collected items.

Only active if GEMINI_API_KEY env var is set. Does NOT block collection
if Gemini is unavailable.

For each item with an empty or short description, Gemini suggests a concise
2-sentence description based on the project name, source, and URL.
"""

import json
from typing import Optional
import requests

from collector import config


def enrich_items(items: list[dict]) -> list[dict]:
    """Enrich items with Gemini-suggested descriptions when enabled.

    Only enriches items that have empty `desc` or missing useful metadata.
    Skips items that already have a decent description.
    Returns the same list (mutated in place where enriched).
    """
    if not config.GEMINI_ENABLED:
        return items

    to_enrich = [it for it in items if not it.get("desc") or len(it.get("desc", "")) < 30]
    if not to_enrich:
        return items

    print(f"  [gemini] enriching {len(to_enrich)} items...")
    enriched = 0
    for it in to_enrich:
        tool = it.get("tool", "")
        source_name = it.get("_source_name", it.get("source", ""))
        source_url = it.get("source_url") or it.get("links", [{}])[0].get("url", "")
        repo_url = it.get("_repo_url") or it.get("links", [{}])[0].get("url", "")

        if not tool:
            continue

        prompt = _build_prompt(tool, source_name, source_url, repo_url)
        result = _call_gemini(prompt)
        if result:
            it["desc"] = result
            enriched += 1

    print(f"  [gemini] enriched {enriched}/{len(to_enrich)} items")
    return items


def _build_prompt(tool: str, source_name: str, source_url: str, repo_url: str) -> str:
    parts = [
        "Write a concise ~2-sentence description of this open-source project or release.",
        "Keep it factual, no marketing language, no speculation.",
        f"Project/tool name: {tool}",
    ]
    if source_name and source_name != "unknown":
        parts.append(f"Source: {source_name}")
    if repo_url:
        parts.append(f"Repository: {repo_url}")
    if source_url and source_url != repo_url:
        parts.append(f"Announcement URL: {source_url}")
    parts.append(
        "Respond with ONLY the description text (no quotes, no markdown, no preamble). "
        "Max 2 sentences, 30-400 characters."
    )
    return "\n".join(parts)


def _call_gemini(prompt: str) -> Optional[str]:
    if not config.GEMINI_ENABLED or not config.GEMINI_API_URL:
        return None
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    try:
        resp = requests.post(
            config.GEMINI_API_URL,
            headers=config.GEMINI_HEADERS,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        candidate = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        if candidate:
            # Trim to reasonable length
            candidate = candidate.strip()
            if len(candidate) > 450:
                candidate = candidate[:447] + "..."
            return candidate
    except requests.RequestException as e:
        print(f"    [gemini error] {e}")
    return None
