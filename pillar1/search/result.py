"""
search/result.py
================
SearchResult — the single data contract shared by every search provider.

Design rules
------------
- No provider-specific fields.  All provider quirks are resolved inside
  the provider before this object is created.
- Every field has a sensible default so providers never have to set fields
  they don't support (controlled by SearchProvider.capabilities).
- `provider_rank` carries the 1-based position within the provider's own
  result list — invaluable for debugging and result-quality analysis.
- `timestamp` is set automatically at construction.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class SearchResult:
    """
    Unified search result returned by every provider.

    Fields
    ------
    title         : Page title (may be None if provider doesn't support titles)
    url           : Canonical result URL (always present)
    snippet       : Short description / excerpt (may be None)
    provider      : Provider slug, e.g. "serpapi", "bing", "google_cse"
    source        : Logical source label, e.g. "LinkedIn", "Clutch", "Google"
    rank          : Global rank within SearchManager's merged result list (1-based)
    provider_rank : 1-based position in THIS provider's own result list.
                    Lets you distinguish Google #1 vs Bing #1 for the same URL.
    query         : The exact query string that produced this result
    page          : Page / offset index used in the provider request
    timestamp     : Unix timestamp (float) when this result was fetched
    """

    # Required
    url: str

    # Common optional fields
    title:         str | None = None
    snippet:       str | None = None

    # Provenance
    provider:      str = "unknown"
    source:        str = ""           # Logical source (LinkedIn, Clutch, …)
    rank:          int = 0            # Filled in by SearchManager after merge
    provider_rank: int = 0            # 1-based position in provider's raw list
    query:         str = ""
    page:          int = 0
    timestamp:     float = field(default_factory=time.time)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return a plain dict (compatible with legacy pipeline dicts)."""
        return {
            "title":         self.title,
            "url":           self.url,
            "snippet":       self.snippet,
            "provider":      self.provider,
            "source":        self.source,
            "rank":          self.rank,
            "provider_rank": self.provider_rank,
            "query":         self.query,
            "page":          self.page,
            "timestamp":     self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SearchResult":
        """Reconstruct from a dict (useful for caching / serialization)."""
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
