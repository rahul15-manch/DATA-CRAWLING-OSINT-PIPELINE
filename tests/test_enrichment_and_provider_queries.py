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
        if t.source not in {"linkedin", "clutch", "goodfirms", "crunchbase", "wellfound", "apollo", "zoominfo", "justdial"}
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
