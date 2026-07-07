
from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse, urlunparse

import config
from search.exceptions import AllProvidersExhausted, ProviderParseError, ProviderUnavailable
from search.provider_base import SearchProvider
from search.registry import DEFAULT_PRIORITY, PROVIDER_REGISTRY
from search.result import SearchResult


# ─────────────────────────────────────────────────────────────────────────────
# Per-provider statistics
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProviderStats:
    """Collected metrics for a single provider during a pipeline run."""

    provider:         str
    queries:          int   = 0
    results_returned: int   = 0
    failures:         int   = 0
    fallback_count:   int   = 0
    total_latency_s:  float = 0.0

    @property
    def success_rate(self) -> float:
        """Fraction of queries that returned at least one result (0.0–1.0)."""
        if self.queries == 0:
            return 0.0
        return (self.queries - self.failures) / self.queries

    @property
    def avg_latency_s(self) -> float:
        if self.queries == 0:
            return 0.0
        return self.total_latency_s / self.queries

    def summary_line(self) -> str:
        return (
            f"  {self.provider:<20}"
            f"  queries={self.queries}"
            f"  results={self.results_returned}"
            f"  failures={self.failures}"
            f"  fallbacks={self.fallback_count}"
            f"  success_rate={self.success_rate:.0%}"
            f"  avg_latency={self.avg_latency_s:.2f}s"
        )


# ─────────────────────────────────────────────────────────────────────────────
# URL canonicalization
# ─────────────────────────────────────────────────────────────────────────────

# UTM and tracking params to strip before deduplication
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referrer", "source", "fbclid", "gclid", "msclkid", "mc_cid",
    "mc_eid", "_ga", "yclid", "dclid",
})


def _canonicalize_url(url: str) -> str:
    """
    Normalize a URL so that semantically identical URLs deduplicate.

    Transformations
    ---------------
    1. Lowercase scheme and host
    2. Strip www. prefix
    3. Remove trailing slash from path (unless path is just "/")
    4. Remove tracking / UTM query parameters
    5. Sort remaining query parameters for stable comparison
    6. Drop empty fragments

    Examples
    --------
    https://Example.com/            → https://example.com
    https://www.example.com         → https://example.com
    https://example.com?utm_source=google → https://example.com
    https://example.com/page/       → https://example.com/page
    """
    try:
        parsed = urlparse(url.strip())

        scheme  = parsed.scheme.lower()
        netloc  = parsed.netloc.lower()

        # Strip www.
        if netloc.startswith("www."):
            netloc = netloc[4:]

        path    = parsed.path.rstrip("/") or ""
        # Preserve root "/" for domains like "https://example.com/"
        # → empty path is fine; just don't duplicate slashes

        # Strip tracking params, sort remaining
        if parsed.query:
            qs_pairs = [
                (k, v)
                for k, vals in parse_qs(parsed.query, keep_blank_values=False).items()
                if k not in _TRACKING_PARAMS
                for v in vals
            ]
            qs_pairs.sort()
            query = "&".join(f"{k}={v}" for k, v in qs_pairs)
        else:
            query = ""

        canonical = urlunparse((scheme, netloc, path, "", query, ""))
        return canonical

    except Exception:
        # If anything goes wrong return the original (never crash deduplication)
        return url.strip()


# ─────────────────────────────────────────────────────────────────────────────
# SearchManager
# ─────────────────────────────────────────────────────────────────────────────

class SearchManager:
    """
    Coordinates all provider interactions for the Flowiz search layer.

    Usage
    -----
    manager = SearchManager()
    results = manager.search("automation company", max_results=10)

    Each element of `results` is a SearchResult with all metadata fields set.
    For backward compatibility, call .to_dict() to get a plain dict.
    """

    def __init__(self) -> None:
        # ── Provider priority list (env-configurable) ─────────────────────
        raw_priority: str = getattr(
            config, "SEARCH_PROVIDER_PRIORITY",
            ",".join(DEFAULT_PRIORITY),
        )
        # Support both list (if already parsed by config.py) and raw string
        if isinstance(raw_priority, list):
            self._priority: list[str] = [p.strip() for p in raw_priority if p.strip()]
        else:
            self._priority = [p.strip() for p in raw_priority.split(",") if p.strip()]

        # ── Provider mode ─────────────────────────────────────────────────
        self._mode: str = getattr(config, "SEARCH_PROVIDER", "auto").strip().lower()

        # ── Lazy provider instance cache ──────────────────────────────────
        self._instances: dict[str, SearchProvider] = {}

        # ── Health tracking — once False, the provider is skipped ─────────
        # Populated as: { "serpapi": True, "bing": True, "google_cse": False }
        self.provider_health: dict[str, bool] = {
            name: True for name in PROVIDER_REGISTRY
        }

        # ── Per-provider statistics ───────────────────────────────────────
        self.stats: dict[str, ProviderStats] = {
            name: ProviderStats(provider=name) for name in PROVIDER_REGISTRY
        }

        # ── Totals ────────────────────────────────────────────────────────
        self.total_queries:            int = 0
        self.total_results:            int = 0
        self.total_duplicates_removed: int = 0
        self.total_merged:             int = 0

        # For backward compatibility — tracks which provider(s) served last call
        self.last_provider_used: str = "none"

    # ── Public API ────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        max_results: int = 10,
        page: int = 0,
    ) -> list[SearchResult]:
        """
        Execute a search and return a merged, deduplicated list of SearchResult.

        Provider selection follows `SEARCH_PROVIDER` and `SEARCH_PROVIDER_PRIORITY`.
        Failover is automatic — unhealthy providers are skipped.

        Parameters
        ----------
        query       : Search query string
        max_results : Maximum results to return (across all providers)
        page        : Zero-based page index

        Returns
        -------
        list[SearchResult] — always returns a list (empty on total failure)
        """
        self.total_queries += 1
        ordered = self._get_ordered_providers()

        all_results:   list[SearchResult] = []
        providers_used: list[str]         = []
        seen_canonical: set[str]          = set()

        for provider in ordered:
            pname = provider.name

            if not self.provider_health.get(pname, True):
                print(f"[SearchManager] Skipping {pname!r} (marked unhealthy this run)")
                continue

            t0 = time.time()
            self.stats[pname].queries += 1

            try:
                print(
                    f"[SearchManager] [{pname}] query='{query}'"
                    f" max_results={max_results} page={page}"
                )
                raw = provider.search(query, max_results=max_results, page=page)
                latency = time.time() - t0
                self.stats[pname].total_latency_s += latency
                self.stats[pname].results_returned += len(raw)

                # Merge into all_results, deduplicating by canonical URL
                accepted = 0
                for r in raw:
                    canon = _canonicalize_url(r.url)
                    if canon in seen_canonical:
                        self.total_duplicates_removed += 1
                        continue
                    seen_canonical.add(canon)
                    all_results.append(r)
                    accepted += 1

                providers_used.append(pname)
                print(
                    f"[SearchManager] [{pname}] latency={latency:.2f}s"
                    f" raw={len(raw)} accepted={accepted}"
                )

                # In auto mode: one successful provider is enough
                if self._mode == "auto" and accepted > 0:
                    break

                # If we have enough results, stop
                if len(all_results) >= max_results:
                    break

            except ProviderUnavailable as exc:
                latency = time.time() - t0
                self.stats[pname].total_latency_s += latency
                self.stats[pname].failures += 1

                # Mark unhealthy — won't be tried again this run
                self.provider_health[pname] = False
                print(f"[SearchManager] [{pname}] UNAVAILABLE — {exc.reason}. Failing over.")

                # Increment fallback_count for every provider that comes AFTER
                # this one in the priority list.  Those providers are being tried
                # *because of* this failure — that's the definition of "fallback".
                # Bug-fix: must index into self.stats (not .get which returns a
                # throwaway object that was never stored).
                try:
                    current_idx = self._priority.index(pname)
                    for next_name in self._priority[current_idx + 1:]:
                        if next_name in self.stats:
                            self.stats[next_name].fallback_count += 1
                except ValueError:
                    pass  # pname not in priority list — harmless
                continue


            except ProviderParseError as exc:
                latency = time.time() - t0
                self.stats[pname].total_latency_s += latency
                self.stats[pname].failures += 1
                print(
                    f"[SearchManager] [{pname}] PARSE ERROR — {exc.reason}."
                    f" Continuing to next provider."
                )
                continue

            except Exception as exc:
                latency = time.time() - t0
                self.stats[pname].total_latency_s += latency
                self.stats[pname].failures += 1
                self.provider_health[pname] = False
                print(f"[SearchManager] [{pname}] UNEXPECTED ERROR — {exc}. Marking unhealthy.")
                continue

        # Assign global ranks
        for global_rank, r in enumerate(all_results[:max_results], start=1):
            r.rank = global_rank

        final = all_results[:max_results]
        self.total_results  += len(final)
        self.total_merged   += len(final)
        self.last_provider_used = " + ".join(providers_used) if providers_used else "none"

        return final

    # ── Statistics ────────────────────────────────────────────────────────────

    def print_stats(self) -> None:
        """Print a formatted per-provider and totals report."""
        print("\n" + "=" * 60)
        print("SEARCH LAYER STATISTICS")
        print("=" * 60)
        print(f"  Total queries    : {self.total_queries}")
        print(f"  Total results    : {self.total_results}")
        print(f"  Duplicates removed: {self.total_duplicates_removed}")
        print(f"  Merged results   : {self.total_merged}")
        print()
        print("  Provider breakdown:")
        for name, s in self.stats.items():
            if s.queries > 0:
                print(s.summary_line())
        print()
        print("  Provider health (end of run):")
        for name, healthy in self.provider_health.items():
            status = "OK  healthy" if healthy else "ERR unhealthy"
            print(f"    {name:<20} {status}")
        print("=" * 60)

    def diagnose(self) -> None:
        """
        Print a human-readable provider readiness report.

        Call this before running the pipeline to understand exactly which
        providers are ready and what config keys are needed for the others.

        Output example
        --------------
        PROVIDER READINESS CHECK
        ========================
          [READY]    bing          — always available (no key required)
          [NO KEY]   serpapi       — set SERPAPI_KEY in .env to enable
          [NO KEY]   google_cse    — set GOOGLE_CSE_KEY + GOOGLE_CSE_CX in .env
          [DISABLED] google_html   — set ENABLE_GOOGLE_HTML=True to enable
          [DISABLED] generic_api   — set ENABLE_CUSTOM_PROVIDER=True + CUSTOM_PROVIDER_URL
        """
        import config as _cfg

        print("\n" + "=" * 60)
        print("PROVIDER READINESS CHECK")
        print("=" * 60)
        print(f"  Mode     : {self._mode}")
        print(f"  Priority : {', '.join(self._priority)}")
        print()

        _HINTS = {
            "serpapi": (
                "SERPAPI_KEY",
                "set SERPAPI_KEY=<your_key> in .env  "
                "(get one free at https://serpapi.com)"
            ),
            "google_cse": (
                "GOOGLE_CSE_KEY + GOOGLE_CSE_CX",
                "set GOOGLE_CSE_KEY=<key> and GOOGLE_CSE_CX=<cx> in .env  "
                "(Google Custom Search JSON API)"
            ),
            "generic_api": (
                "ENABLE_CUSTOM_PROVIDER + CUSTOM_PROVIDER_URL",
                "set ENABLE_CUSTOM_PROVIDER=True and CUSTOM_PROVIDER_URL=<url> in .env"
            ),
            "google_html": (
                "ENABLE_GOOGLE_HTML",
                "set ENABLE_GOOGLE_HTML=True in .env  "
                "[experimental — Google actively blocks HTML scrapers]"
            ),
            "bing": (
                None,
                "always available — no key required"
            ),
        }

        ready_count = 0
        for name, cls in PROVIDER_REGISTRY.items():
            instance = self._get_instance(name)
            available = instance.is_available()
            caps      = instance.capabilities
            hint_key, hint_msg = _HINTS.get(name, (None, "see provider docs"))

            if available:
                status = "[READY]   "
                detail = "available"
                ready_count += 1
            else:
                # Figure out WHY it's not available
                enable_flag = f"ENABLE_{name.upper()}"
                flag_val    = getattr(_cfg, enable_flag, None)

                if flag_val is False:
                    status = "[DISABLED]"
                else:
                    status = "[NO KEY]  "
                detail = hint_msg

            in_priority = name in self._priority
            priority_tag = "" if in_priority else "  [not in priority list]"
            print(f"  {status} {name:<20} {detail}{priority_tag}")

        print()
        if ready_count == 0:
            print("  WARNING: No providers are ready.  Searches will return empty results.")
            print("  At minimum, Bing must be enabled (ENABLE_BING=True).")
        else:
            active = [
                name for name in self._priority
                if name in PROVIDER_REGISTRY and self._get_instance(name).is_available()
            ]
            print(f"  Active provider order: {' -> '.join(active) if active else 'none'}")
        print("=" * 60 + "\n")



    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_ordered_providers(self) -> list[SearchProvider]:
        """
        Return provider instances in the order they should be tried.

        - Respects SEARCH_PROVIDER_PRIORITY
        - Filters out providers not in PROVIDER_REGISTRY
        - Filters out providers whose is_available() == False
        """
        ordered: list[SearchProvider] = []

        for name in self._priority:
            if name not in PROVIDER_REGISTRY:
                print(f"[SearchManager] Warning: unknown provider {name!r} in priority list")
                continue
            instance = self._get_instance(name)
            if not instance.is_available():
                print(f"[SearchManager] [{name}] not available (config/credentials check failed)")
                continue
            ordered.append(instance)

        if not ordered:
            print(
                "[SearchManager] Warning: no providers are available. "
                "Check config keys and ENABLE_* flags."
            )

        return ordered

    def _get_instance(self, name: str) -> SearchProvider:
        """Return a cached provider instance, creating it on first use."""
        if name not in self._instances:
            cls = PROVIDER_REGISTRY[name]
            self._instances[name] = cls()
        return self._instances[name]


# ─────────────────────────────────────────────────────────────────────────────
# Global singleton + backward-compat shim
# ─────────────────────────────────────────────────────────────────────────────

_manager: SearchManager | None = None


def get_search_manager() -> SearchManager:
    """Return the global SearchManager singleton (created on first call)."""
    global _manager
    if _manager is None:
        _manager = SearchManager()
    return _manager


def run_search(
    query: str,
    max_results: int | None = None,
    start: int = 0,
) -> list[dict]:
    """
    Backward-compatibility shim.

    discovery/company_discovery.py and contact_discovery.py call this
    function exactly as before.  It returns plain dicts (not SearchResult
    objects) so the rest of the pipeline doesn't need to change.

    Parameters
    ----------
    query       : Search query string
    max_results : Maximum results (defaults to config.MAX_RESULTS_PER_QUERY)
    start       : Result offset → converted to page index
    """
    max_r  = max_results or getattr(config, "MAX_RESULTS_PER_QUERY", 10)
    page   = start // max_r if max_r else 0
    manager = get_search_manager()
    results = manager.search(query, max_results=max_r, page=page)
    return [r.to_dict() for r in results]
