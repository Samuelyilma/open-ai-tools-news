"""Open Tool Drop — automated open-source news collector.

Modules:
  models     — Item dataclass + site-format conversion
  config     — source config, env vars, watchlist loading
  sources    — GitHub Releases, GitHub Search, Hacker News
  filter     — quality gate + duplicate detection
  storage    — news.json / seen.json / watchlist.json persistence
  enrich     — optional Gemini description enrichment
  run        — CLI runner (collect | review | status | watchlist | watch-add | watch-remove)
"""

__version__ = "1.0.0"
