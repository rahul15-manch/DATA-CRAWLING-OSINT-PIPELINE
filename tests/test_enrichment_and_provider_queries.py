from extraction.page_extractor import find_subpages
from query.dork_generator import generate_search_tasks
from query.expansion import build_semantic_company_variants, get_query_feedback_weight, record_query_outcome
from search.providers.directory_provider import _build_query_candidates


def test_build_query_candidates_expands_company_intent():
    candidates = _build_query_candidates("python")
    assert "python" in candidates


def test_find_subpages_detects_careers_and_privacy_links():
    html = """
    <html><body>
      <a href="/careers">Careers</a>
      <a href="/privacy-policy">Privacy Policy</a>
      <a href="/about">About</a>
    </body></html>
    """
    subpages = find_subpages(html, "https://example.com")
    assert subpages["careers_page"] == "https://example.com/careers"
    assert subpages["privacy_page"] == "https://example.com/privacy-policy"


def test_generate_search_tasks_avoids_restrictive_site_queries():
    tasks = generate_search_tasks("python")
    over_restricted_queries = [
        t.query for t in tasks
        if t.source not in {"linkedin", "clutch", "goodfirms", "crunchbase", "wellfound", "apollo", "zoominfo", "justdial", "github"}
        and "site:" in t.query and not "-site:" in t.query
    ]
    assert not over_restricted_queries


def test_semantic_variants_prioritize_broad_company_intent():
    variants = build_semantic_company_variants("python")
    assert variants[0] == "python"
    assert "python software company" in variants
    assert "python development company" in variants
    assert "python consulting firm" in variants


def test_query_feedback_penalizes_repeated_zero_results():
    query = "site:clutch.co python company"
    baseline = get_query_feedback_weight(query)

    for _ in range(30):
        record_query_outcome(query, "zero_result", 0)

    assert get_query_feedback_weight(query) < baseline


def test_subpage_filtering_rejects_transactional_and_auth_urls():
    from extraction.page_extractor import is_disallowed_subpage_url, find_subpages
    assert is_disallowed_subpage_url("https://swiggy.com/checkout")
    assert is_disallowed_subpage_url("https://swiggy.com/cart")
    assert is_disallowed_subpage_url("https://swiggy.com/auth")
    assert is_disallowed_subpage_url("https://swiggy.com/my-account/orders")
    assert is_disallowed_subpage_url("https://pizzahut.com/order/deal")
    assert not is_disallowed_subpage_url("https://swiggy.com/about")
    assert not is_disallowed_subpage_url("https://swiggy.com/contact-us")
    assert not is_disallowed_subpage_url("https://swiggy.com/leadership-team")

    html = """
    <html><body>
      <a href="/checkout">Checkout</a>
      <a href="/cart">Cart</a>
      <a href="/contact">Contact</a>
      <a href="/about">About Us</a>
      <a href="/auth/login">Login</a>
    </body></html>
    """
    subpages = find_subpages(html, "https://swiggy.com")
    assert "checkout" not in str(subpages)
    assert "cart" not in str(subpages)
    assert "auth" not in str(subpages)
    assert subpages.get("contact_page") == "https://swiggy.com/contact"
    assert subpages.get("about_page") == "https://swiggy.com/about"
