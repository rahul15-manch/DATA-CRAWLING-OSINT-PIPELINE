from __future__ import annotations
import config
from urllib.parse import quote_plus
from search.providers.google_html_provider import GoogleHtmlProvider
from search.provider_base import Capabilities
from search.search_validator import SearchValidationResult
from search.result import SearchResult
from search.google_response_classifier import classify_google_response
from search.google_parser_registry import GoogleParserRegistry
from network_client_project.network.middleware.base import Request
import time

class BrightDataProvider(GoogleHtmlProvider):

    name = "brightdata"

    capabilities = Capabilities(
        supports_pagination  = True,
        supports_snippets    = True,
        supports_titles      = True,
        supports_rate_limit  = True,
        max_results_per_page = 10,
    )

    def is_available(self) -> bool:
        return bool(
            getattr(config, "ENABLE_BRIGHTDATA", True)
            and getattr(config, "BRIGHTDATA_KEY", "")
            and getattr(config, "BRIGHTDATA_ZONE", "")
        )

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

        results, _ = self._execute_search_query(query, max_results, page)
        return results

    def _execute_search_query(
        self,
        query: str,
        max_results: int,
        page: int,
        session_id: str = "brightdata",
    ) -> tuple[list[SearchResult], SearchValidationResult]:
        from search.search_validator import validate_search_response

        params = f"q={quote_plus(query)}&num={min(max_results, 10)}&hl=en&gl=us"
        if page > 0:
            params += f"&start={page * min(max_results, 10)}"
        google_url = f"https://www.google.com/search?{params}"

        headers = {
            "Authorization": f"Bearer {config.BRIGHTDATA_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "zone": config.BRIGHTDATA_ZONE,
            "url": google_url,
            "format": "raw"
        }

        try:
            resp = self._client.post(
                "https://api.brightdata.com/request",
                headers=headers,
                json=payload,
                require_proxy=False,
                bypass_proxy=True,
                timeout=60.0
            )
            resp.raise_for_status()
        except Exception as exc:
            return [], SearchValidationResult("NETWORK_FAILURE", 0, "NETWORK_ERROR", str(exc))

        html = resp.text
        html_size = len(html)

        from search.manager import get_search_manager
        sm = get_search_manager()
        sm.google_requests_sent += 1
        sm.google_html_sizes.append(html_size)

        # 1. Advanced Response Classification
        analysis = classify_google_response(html, resp.status_code, google_url)
        classification = analysis["page_type"]
        
        print(f"\n[BrightDataProvider] HTML size: {html_size:,} bytes")
        print(f"  Detected Page:    {classification} (Confidence: {analysis['confidence_score']:.2f})")
        print(f"  Fingerprint:      {analysis['layout_fingerprint']}")
        print(f"  Detected Language: {analysis['language']}")
        if analysis["detected_signals"]:
            print(f"  Signals:          {', '.join(analysis['detected_signals'])}")

        self._archive_sample(resp, analysis, query)

        # 2. Parser Cascade (Try to extract first, even if classified as CONSENT_PAGE or similar)
        parsers = GoogleParserRegistry.get_parsers()
        results = []
        succeeded_parser = None
        cascade_log_items = []

        print("\n[BrightDataProvider] Executing parser cascade:")
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
                r.provider = self.name
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

        cascade_str = " -> ".join(cascade_log_items)
        print(f"\n[BrightDataProvider] Cascade: {cascade_str}")

        if results:
            sm.google_successful_serps += 1
            print(f"[BrightDataProvider] Succeeded via {succeeded_parser}!\n")
            return results, SearchValidationResult(
                "VALID_RESULTS", len(results), classification,
                failure_reason=None
            )

        # 3. If no results found, evaluate layout classification early returns
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
            print("[BrightDataProvider] Google search returned 0 organic matches.")
            return [], SearchValidationResult("VALID_ZERO_RESULTS", 0, classification)
        elif classification == "EMPTY_SERP":
            sm.google_unknown_layouts += 1
            return [], SearchValidationResult("NETWORK_FAILURE", 0, classification, "Empty HTML payload returned")
        validation_result = validate_search_response("google_html", html, resp.status_code, google_url, [])
        if validation_result.status == "PARSER_FAILURE":
            sm.google_parser_failures += 1
        else:
            sm.google_parser_failures += 1
            sm.google_unknown_layouts += 1

        return [], validation_result
