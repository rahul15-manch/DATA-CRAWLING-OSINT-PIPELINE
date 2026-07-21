import logging
from dataclasses import dataclass
from search.google_response_classifier import classify_google_response

logger = logging.getLogger(__name__)

@dataclass
class SearchValidationResult:
    status: str  # VALID_RESULTS, VALID_ZERO_RESULTS, CAPTCHA, RATE_LIMIT, PARSER_FAILURE, UNKNOWN_LAYOUT, NETWORK_FAILURE, ENABLE_JS, CONSENT_PAGE
    result_count: int
    classification: str
    failure_reason: str | None = None

def validate_search_response(provider_name: str, html: str, status_code: int, url: str, results: list) -> SearchValidationResult:
    """
    Validates and classifies a search provider response into a SearchValidationResult.
    """
    if not html:
        return SearchValidationResult(
            status="NETWORK_FAILURE",
            result_count=0,
            classification="EMPTY_HTML",
            failure_reason="Empty HTML payload returned"
        )

    if status_code == 429:
        return SearchValidationResult(
            status="RATE_LIMIT",
            result_count=0,
            classification="HTTP_429",
            failure_reason="HTTP 429 rate limit exceeded"
        )

    if provider_name == "google_html":
        if status_code == 403:
            return SearchValidationResult(
                status="FORBIDDEN",
                result_count=0,
                classification="FORBIDDEN_PAGE",
                failure_reason="Google returned HTTP 403 Forbidden"
            )

        analysis = classify_google_response(html, status_code, url)
        page_type = analysis["page_type"]

        if page_type == "CAPTCHA_PAGE":
            return SearchValidationResult(
                status="CAPTCHA",
                result_count=0,
                classification=page_type,
                failure_reason="Google unusual traffic / CAPTCHA page detected"
            )
        elif page_type == "ENABLE_JS_PAGE":
            return SearchValidationResult(
                status="ENABLE_JS",
                result_count=0,
                classification=page_type,
                failure_reason="Google JavaScript redirection requested"
            )
        elif page_type == "CONSENT_PAGE":
            return SearchValidationResult(
                status="CONSENT_PAGE",
                result_count=0,
                classification=page_type,
                failure_reason="Google cookie consent wall redirected"
            )
        elif page_type == "GOOGLE_SORRY_PAGE":
            return SearchValidationResult(
                status="RATE_LIMIT",
                result_count=0,
                classification=page_type,
                failure_reason="Google Sorry/429 page displayed"
            )
        elif page_type == "ZERO_RESULTS_PAGE":
            return SearchValidationResult(
                status="VALID_ZERO_RESULTS",
                result_count=0,
                classification=page_type
            )
        
        if results:
            return SearchValidationResult(
                status="VALID_RESULTS",
                result_count=len(results),
                classification=page_type
            )
            
        if page_type in ["NORMAL_DESKTOP_SERP", "NORMAL_MOBILE_SERP", "AI_OVERVIEW_PAGE", "KNOWLEDGE_PANEL_PAGE", "FEATURED_SNIPPET_PAGE", "PEOPLE_ALSO_ASK_PAGE"]:
            return SearchValidationResult(
                status="PARSER_FAILURE",
                result_count=0,
                classification=page_type,
                failure_reason="All parsing strategies failed on recognized search layout"
            )
            
        return SearchValidationResult(
            status="UNKNOWN_LAYOUT",
            result_count=0,
            classification=page_type,
            failure_reason=f"Unrecognized layout layout_{analysis['layout_fingerprint'][:8]}"
        )

    elif provider_name == "bing":
        html_lower = html.lower()
        
        # Menlo Security / safeview check
        if "menlo.gutsenv.net" in html_lower or "safeview" in html_lower or "menlosecurity" in html_lower or "sv_role=" in html_lower:
            return SearchValidationResult(
                status="CAPTCHA",
                result_count=0,
                classification="MENLO_INTERCEPT",
                failure_reason="Menlo Security safeview proxy intercept detected"
            )

        if "captcha" in html_lower or "security check" in html_lower or "please complete" in html_lower:
            return SearchValidationResult(
                status="CAPTCHA",
                result_count=0,
                classification="BING_CAPTCHA",
                failure_reason="Bing CAPTCHA / security check page detected"
            )
            
        if results:
            return SearchValidationResult(
                status="VALID_RESULTS",
                result_count=len(results),
                classification="BING_NORMAL_SERP"
            )

        url_lower = url.lower() if url else ""
        is_consent_url = "consent.bing.com" in url_lower or "/consent" in url_lower
        has_consent_element = (
            "bnp_cookie_banner" in html_lower or 
            "bnp_container" in html_lower or 
            "/consent/accept" in html_lower
        )
        if is_consent_url or has_consent_element:
            return SearchValidationResult(
                status="CONSENT_PAGE",
                result_count=0,
                classification="BING_CONSENT",
                failure_reason="Bing cookie consent page redirect detected"
            )
            
        if "no results found" in html_lower or "did not match any documents" in html_lower:
            return SearchValidationResult(
                status="VALID_ZERO_RESULTS",
                result_count=0,
                classification="BING_ZERO_RESULTS"
            )
            
        if "sb_form" in html_lower or "b_results" in html_lower:
            return SearchValidationResult(
                status="PARSER_FAILURE",
                result_count=0,
                classification="BING_PARSER_FAILURE",
                failure_reason="Bing organic elements did not match any documents"
            )
            
        return SearchValidationResult(
            status="UNKNOWN_LAYOUT",
            result_count=0,
            classification="BING_UNKNOWN_LAYOUT",
            failure_reason="Bing unknown HTML layout signature detected"
        )

    return SearchValidationResult(
        status="UNKNOWN_LAYOUT",
        result_count=0,
        classification="UNKNOWN",
        failure_reason="Unknown provider layout"
    )
