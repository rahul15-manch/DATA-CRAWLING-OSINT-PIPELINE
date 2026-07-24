import time
import threading
import random
import config
import re
import os
import json
from datetime import datetime
from urllib.parse import parse_qs, quote_plus, urlparse
from bs4 import BeautifulSoup

from pillar3_network_resilience.network import NetworkClient
from pillar3_network_resilience.network.exceptions import NetworkClientError
from search.exceptions import (
    ProviderParseError, ProviderUnavailable,
    CaptchaDetectedError, EnableJSDetectedError,
    ConsentPageDetectedError, GoogleSorryPageDetectedError
)
from search.google_response_classifier import classify_google_response
from search.google_parser_registry import GoogleParserRegistry
from search.search_validator import SearchValidationResult
from search.provider_base import Capabilities, SearchProvider
from search.result import SearchResult
from pillar3_network_resilience.network.middleware.base import Request

_SKIP_DOMAINS = frozenset({
    "google.com", "google.co.in", "google.co.uk",
    "googleadservices.com", "doubleclick.net",
    "youtube.com",
    "maps.google.com",
    "support.google.com",
    "accounts.google.com",
})

_SKIP_BLOCK_CLASSES = frozenset({
    "uEierd",
    "commercial-unit-desktop-top",
    "ads-ad",
    "related-question-pair",
    "g-blk",
    "ULSxyf",
    "nDgy9d",
    "ueGUFe",
    "sh-dlr__list-result",
    "g-inner-card",
    "X5OiLe",
    "RzdJxc",
    "iKFuM",
    "AJLUJb",
})


class GoogleHtmlProvider(SearchProvider):

    name = "google_html"

    capabilities = Capabilities(
        supports_pagination  = True,
        supports_snippets    = True,
        supports_titles      = True,
        supports_rate_limit  = True,
        max_results_per_page = 10,
    )

    _concurrency_lock = threading.Semaphore(config.GOOGLE_MAX_CONCURRENT)

    _SEARCH_URL = "https://www.google.com/search"

    def __init__(self, network_client: NetworkClient | None = None):
        self._client = network_client or NetworkClient()

    def is_available(self) -> bool:
        return True

    def search(
        self,
        request_or_query: Request | str,
        max_results: int = 10,
        page: int = 0,
    ) -> list[SearchResult]:
        if isinstance(request_or_query, Request):
            query = request_or_query.query or ""
            page = request_or_query.meta.get("page", 0)
            max_results = request_or_query.meta.get("max_results", 10)
        else:
            query = request_or_query

        from search.google_scheduler import GoogleRequestScheduler
        scheduler = GoogleRequestScheduler()
        return scheduler.schedule_search(query, max_results, page, self)

    def _execute_search_query(
        self,
        query: str,
        max_results: int,
        page: int,
        session_id: str = "google_html",
    ) -> tuple[list[SearchResult], SearchValidationResult]:
        from search.search_validator import validate_search_response, SearchValidationResult

        params = f"q={quote_plus(query)}&num={min(max_results, 10)}&hl=en&gl=us"
        if page > 0:
            params += f"&start={page * min(max_results, 10)}"
        url = f"{self._SEARCH_URL}?{params}"

        try:
            resp = self._client.get(url, session_id=session_id, require_proxy=True, auto_score=False, timeout=8.0, provider="google_html")
            resp.raise_for_status()
        except CaptchaDetectedError as exc:
            return [], SearchValidationResult("CAPTCHA", 0, "CAPTCHA_PAGE", str(exc))
        except EnableJSDetectedError as exc:
            return [], SearchValidationResult("ENABLE_JS", 0, "ENABLE_JS_PAGE", str(exc))
        except ConsentPageDetectedError as exc:
            return [], SearchValidationResult("CONSENT_PAGE", 0, "CONSENT_PAGE", str(exc))
        except GoogleSorryPageDetectedError as exc:
            return [], SearchValidationResult("RATE_LIMIT", 0, "SORRY_PAGE", str(exc))
        except NetworkClientError as exc:
            return [], SearchValidationResult("NETWORK_FAILURE", 0, "NETWORK_ERROR", str(exc))
        except Exception as exc:
            return [], SearchValidationResult("NETWORK_FAILURE", 0, "NETWORK_ERROR", str(exc))

        html = resp.text
        html_size = len(html)

        from search.manager import get_search_manager
        sm = get_search_manager()
        sm.google_requests_sent += 1
        sm.google_html_sizes.append(html_size)

        # 1. Advanced Response Classification
        analysis = classify_google_response(html, resp.status_code, resp.url)
        classification = analysis["page_type"]
        
        print(f"\n[GoogleHtmlProvider] HTML size: {html_size:,} bytes")
        print(f"  Detected Page:    {classification} (Confidence: {analysis['confidence_score']:.2f})")
        print(f"  Fingerprint:      {analysis['layout_fingerprint']}")
        print(f"  Detected Language: {analysis['language']}")
        if analysis["detected_signals"]:
            print(f"  Signals:          {', '.join(analysis['detected_signals'])}")

        # Archive sample under categorized folders with full metadata
        self._archive_sample(resp, analysis, query)

        # Remove global consecutive zero results block

        # Handle non-SERP page types — do NOT penalize proxy for these
        if classification == "CAPTCHA_PAGE":
            sm.google_captchas += 1
            return [], SearchValidationResult("CAPTCHA", 0, classification, "Google unusual traffic / CAPTCHA page detected")
        elif classification == "ENABLE_JS_PAGE":
            sm.google_enable_js_queries += 1
            return [], SearchValidationResult("ENABLE_JS", 0, classification, "Google JavaScript redirection requested")
        elif classification == "CONSENT_PAGE":
            sm.google_consent_pages += 1
            return [], SearchValidationResult("CONSENT_PAGE", 0, classification, "Google cookie consent wall redirected")
        elif classification in ("SORRY_PAGE", "GOOGLE_SORRY_PAGE"):
            sm.google_429s += 1
            return [], SearchValidationResult("RATE_LIMIT", 0, classification, "Google Sorry/429 rate limit page displayed")
        elif classification == "ZERO_RESULTS_PAGE":
            sm.google_successful_serps += 1
            print("[GoogleHtmlProvider] Google search returned 0 organic matches.")
            return [], SearchValidationResult("VALID_ZERO_RESULTS", 0, classification)
        elif classification == "EMPTY_SERP":
            sm.google_unknown_layouts += 1
            return [], SearchValidationResult("NETWORK_FAILURE", 0, classification, "Empty HTML payload returned")

        # 2. Registry-Driven Multi-Parser Cascade (fixed order)
        parsers = GoogleParserRegistry.get_parsers()
        results = []
        succeeded_parser = None
        cascade_log_items = []

        print("\n[GoogleHtmlProvider] Executing parser cascade:")
        for parser in parsers:
            t_start = time.time()
            try:
                raw_extracted = parser.parse(html, max_results, query, page)
            except Exception as parse_exc:
                raw_extracted = []
                print(f"  - {parser.name}: Exception ({parse_exc})")

            elapsed_ms = (time.time() - t_start) * 1000

            # Quality filter
            validated = []
            rejected_count = 0
            for r in raw_extracted:
                quality = self._validate_and_classify_result(r)
                if quality == "Rejected":
                    rejected_count += 1
                else:
                    validated.append(r)

            if validated:
                results = validated
                succeeded_parser = parser.name
                GoogleParserRegistry.record_success(parser.name, elapsed_ms)
                cascade_log_items.append(f"{parser.name} ({len(results)} results, {elapsed_ms:.1f}ms)")
                print(f"  - {parser.name}: Succeeded ({len(results)} results, {elapsed_ms:.1f}ms) [Rejected: {rejected_count}]")
                break
            else:
                GoogleParserRegistry.record_failure(parser.name)
                cascade_log_items.append(f"{parser.name} (0 results, {elapsed_ms:.1f}ms)")
                print(f"  - {parser.name}: Failed (0 results, {elapsed_ms:.1f}ms) [Rejected: {rejected_count}]")

        # Log complete cascade summary
        cascade_str = " -> ".join(cascade_log_items)
        print(f"\n[GoogleHtmlProvider] Cascade: {cascade_str}")

        if results:
            sm.google_successful_serps += 1
            print(f"[GoogleHtmlProvider] Succeeded via {succeeded_parser}!\n")
            return results, SearchValidationResult(
                "VALID_RESULTS", len(results), classification,
                failure_reason=None
            )

        # 3. All parsers failed — classify as PARSER_FAILURE (NOT a proxy issue)
        # Do NOT rotate the proxy; this is a parser compatibility problem.
        validation_result = validate_search_response("google_html", html, resp.status_code, resp.url, [])
        if validation_result.status == "PARSER_FAILURE":
            sm.google_parser_failures += 1
        else:
            sm.google_parser_failures += 1
            sm.google_unknown_layouts += 1

        return [], validation_result

    # ── Result Quality Classifier ─────────────────────────────────────────────

    def _validate_and_classify_result(self, r: SearchResult) -> str:
        """Classify result quality: Accepted, Rejected, Suspicious."""
        if not r.url or not (r.url.startswith("http://") or r.url.startswith("https://")):
            return "Rejected"
        if self._is_skip_domain(r.url) or "/search?" in r.url or "google.com" in r.url:
            return "Rejected"
        if not r.title or not r.title.strip():
            return "Suspicious"
        if not r.snippet or not r.snippet.strip():
            return "Suspicious"
        return "Accepted"

    # ── Parsing Strategies ────────────────────────────────────────────────────

    def _parse_css(self, html: str, max_results: int, query: str, page: int) -> list[SearchResult]:
        """CSSParser: Extracts standard div.g block containers."""
        soup = BeautifulSoup(html, "html.parser")
        for cls in _SKIP_BLOCK_CLASSES:
            for el in soup.select(f".{cls}"):
                el.decompose()
        for el in soup.select("g-section-with-header, .dDajDf, .commercial-unit-desktop-top"):
            el.decompose()

        results = []
        ts = time.time()
        rank = 0
        g_blocks = soup.select("div.g")
        if g_blocks:
            for g in g_blocks:
                r = self._extract_from_block(g, query, page, ts)
                if r:
                    rank += 1
                    r.provider_rank = rank
                    results.append(r)
                    if len(results) >= max_results:
                        break
        return results

    def _parse_xpath(self, html: str, max_results: int, query: str, page: int) -> list[SearchResult]:
        """XPathParser: Extracts div.yuRUbf structured elements."""
        soup = BeautifulSoup(html, "html.parser")
        results = []
        ts = time.time()
        rank = 0
        y_blocks = soup.select("div.yuRUbf")
        for y in y_blocks:
            a = y.select_one("a[href]")
            if not a:
                continue
            href = self._normalize_url(a.get("href"))
            if not href or self._is_skip_domain(href):
                continue
            h3 = a.select_one("h3")
            title = h3.get_text(" ", strip=True) if h3 else a.get_text(" ", strip=True)
            snippet = ""
            parent = y.find_parent("div", class_="g")
            if parent:
                snip_el = parent.select_one("div.VwiC3b, div.yDqZbe, span.aCOpbc")
                if snip_el:
                    snippet = snip_el.get_text(" ", strip=True)
            rank += 1
            results.append(SearchResult(
                url=href, title=title or None,
                snippet=snippet[:400] if snippet else None,
                provider=self.name, source="Google",
                provider_rank=rank, query=query, page=page, timestamp=ts,
            ))
            if len(results) >= max_results:
                break
        return results

    def _parse_semantic(self, html: str, max_results: int, query: str, page: int) -> list[SearchResult]:
        """SemanticParser: Extracts header-centric links (h3 inside anchor tags)."""
        soup = BeautifulSoup(html, "html.parser")
        results = []
        ts = time.time()
        rank = 0
        for a in soup.select("a[href]"):
            href = self._normalize_url(a.get("href"))
            if not href or self._is_skip_domain(href) or href.startswith("/"):
                continue
            h3 = a.select_one("h3")
            if not h3:
                continue
            title = h3.get_text(" ", strip=True)
            parent = a.find_parent("div")
            snippet = parent.get_text(" ", strip=True).replace(title, "", 1).strip() if parent else ""
            rank += 1
            results.append(SearchResult(
                url=href, title=title or None,
                snippet=snippet[:400] if snippet else None,
                provider=self.name, source="Google",
                provider_rank=rank, query=query, page=page, timestamp=ts,
            ))
            if len(results) >= max_results:
                break
        return results

    def _parse_structured_data(self, html: str, max_results: int, query: str, page: int) -> list[SearchResult]:
        """StructuredDataParser: Extract search results out of JSON-LD schemas."""
        results = []
        soup = BeautifulSoup(html, "html.parser")
        ts = time.time()
        rank = 0
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get("@type") == "ItemList":
                    items = data.get("itemListElement", [])
                    for item in items:
                        url = item.get("url")
                        title = item.get("name")
                        if url and title:
                             results.append(SearchResult(
                                 url=url, title=title, snippet=None,
                                 provider=self.name, source="Google",
                                 provider_rank=rank+1, query=query, page=page, timestamp=ts
                             ))
                             rank += 1
                             if len(results) >= max_results:
                                 return results
            except Exception:
                continue
        return results

    def _parse_generic_anchor(self, html: str, max_results: int, query: str, page: int) -> list[SearchResult]:
        """GenericAnchorParser: Extracts raw links that aren't skipped."""
        soup = BeautifulSoup(html, "html.parser")
        results = []
        ts = time.time()
        rank = 0
        for a in soup.select("a[href]"):
            href = self._normalize_url(a.get("href"))
            if not href or self._is_skip_domain(href) or href.startswith("/"):
                continue
            title = a.get_text(" ", strip=True)
            if len(title) < 5:
                continue
            rank += 1
            results.append(SearchResult(
                url=href, title=title or None,
                snippet=None,
                provider=self.name, source="Google",
                provider_rank=rank, query=query, page=page, timestamp=ts,
            ))
            if len(results) >= max_results:
                break
        return results

    def _parse_experimental(self, html: str, max_results: int, query: str, page: int) -> list[SearchResult]:
        """ExperimentalParser: Fallback CSS selectors MjjYud blocks."""
        soup = BeautifulSoup(html, "html.parser")
        results = []
        ts = time.time()
        rank = 0
        for a in soup.select("div.MjjYud a[href]"):
            href = self._normalize_url(a.get("href"))
            if not href or self._is_skip_domain(href) or href.startswith("/"):
                continue
            h3 = a.select_one("h3")
            if not h3:
                continue
            title = h3.get_text(" ", strip=True)
            rank += 1
            results.append(SearchResult(
                url=href, title=title or None,
                snippet=None,
                provider=self.name, source="Google",
                provider_rank=rank, query=query, page=page, timestamp=ts,
            ))
            if len(results) >= max_results:
                break
        return results

    def _extract_from_block(
        self,
        block,
        query: str,
        page: int,
        ts: float,
    ) -> SearchResult | None:
        if block.get("data-sokoban-container") or block.get("data-hveid") == "":
            return None
        a = block.select_one("a[href]")
        if not a:
            return None
        href = self._normalize_url(a.get("href"))
        if not href or self._is_skip_domain(href):
            return None
        h3 = a.select_one("h3")
        title = h3.get_text(" ", strip=True) if h3 else a.get_text(" ", strip=True)
        if not title:
            return None
        snip_el = block.select_one(
            "div.VwiC3b, div.yDqZbe, span.aCOpbc, div.hb85Bf, div.MU1Yt, span.MU1Yt, div.lEBKkf"
        )
        snippet = snip_el.get_text(" ", strip=True) if snip_el else block.get_text(" ", strip=True).replace(title, "", 1).strip()
        return SearchResult(
            url=href,
            title=title,
            snippet=snippet[:400] if snippet else None,
            provider=self.name,
            source="Google",
            provider_rank=0,
            query=query,
            page=page,
            timestamp=ts,
        )

    def _normalize_url(self, href: str | None) -> str | None:
        if not href:
            return None
        href = href.strip()
        if href.startswith("/url?"):
            params = parse_qs(urlparse(href).query)
            if "q" in params:
                return params["q"][0]
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"}:
            return href
        return None

    def _is_skip_domain(self, url: str) -> bool:
        try:
            host = urlparse(url).netloc.lower().lstrip("www.")
            return any(host == d or host.endswith("." + d) for d in _SKIP_DOMAINS)
        except Exception:
            return False

    def _archive_sample(self, resp, analysis: dict, query: str) -> None:
        import os
        import json
        from datetime import datetime
        
        classification = analysis.get("page_type", "UNKNOWN")
        html = resp.text
        
        category_map = {
            "CAPTCHA_PAGE": "Captcha",
            "CONSENT_PAGE": "Consent",
            "ENABLE_JS_PAGE": "EnableJS",
            "SORRY_PAGE": "Sorry",
            "ZERO_RESULTS_PAGE": "ZeroResults",
            "NORMAL_DESKTOP_SERP": "SERP",
            "NORMAL_MOBILE_SERP": "SERP",
            "AI_OVERVIEW_PAGE": "SERP",
            "KNOWLEDGE_PANEL_PAGE": "SERP",
            "FEATURED_SNIPPET_PAGE": "SERP",
            "PEOPLE_ALSO_ASK_PAGE": "SERP",
        }
        subfolder = category_map.get(classification, "Unknown")
        folder_path = f"debug_html/{subfolder}"
        os.makedirs(folder_path, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_query = re.sub(r'[^a-zA-Z0-9]', '_', query)[:30]
        base_filename = f"{folder_path}/{timestamp}_{safe_query}"
        
        try:
            with open(f"{base_filename}.html", "w", encoding="utf-8") as f:
                f.write(html)
                
            redirect_chain = [str(r.url) for r in getattr(resp, "history", [])] + [str(resp.url)]
                
            metadata = {
                "timestamp": datetime.now().isoformat(),
                "query": query,
                "classification": classification,
                "url": str(resp.url),
                "status_code": resp.status_code,
                "redirect_chain": redirect_chain,
                "response_headers": dict(resp.headers),
                "layout_fingerprint": analysis.get("layout_fingerprint"),
                "detected_signals": analysis.get("detected_signals", [])
            }
            
            with open(f"{base_filename}.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
                
            print(f"[GoogleHtmlProvider] Archived HTML and metadata under {folder_path}.")
        except Exception as e:
            print(f"[GoogleHtmlProvider] Error archiving sample: {e}")
