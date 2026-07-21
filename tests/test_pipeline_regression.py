import pytest
import os
import json
from unittest.mock import MagicMock, patch

from semantic.semantic_profile import CompanyProfile, IntentProfile
from semantic.semantic_cache import get_cached_company, set_cached_company, _get_company_cache_key
from semantic.company_semantic_extractor import CompanySemanticExtractor
from discovery.semantic_ranking_engine import SemanticRanker
from utils.stats_tracker import record_rejection, clear_rejections, get


def test_distinct_cache_keys_for_same_platform_domain():
    url1 = "https://www.linkedin.com/company/pythondeveloper"
    url2 = "https://www.linkedin.com/company/java-saas"
    url3 = "https://www.pybuddy.com"
    
    # Platform domain check should produce distinct keys
    key1 = _get_company_cache_key(url1)
    key2 = _get_company_cache_key(url2)
    key3 = _get_company_cache_key(url3)
    
    assert key1 == "https://www.linkedin.com/company/pythondeveloper"
    assert key2 == "https://www.linkedin.com/company/java-saas"
    assert key3 == "pybuddy.com"
    assert key1 != key2


def test_website_extraction_and_attribution():
    extractor = CompanySemanticExtractor()
    
    # Mock LinkedIn HTML profile containing redirect URL
    linkedin_html = """
    <html><body>
      <a href="https://www.linkedin.com/redir/redirect?url=https%3A%2F%2Fpybuddy%2Ecom&urlhash=abc">Website Link</a>
    </body></html>
    """
    
    # Mock Clutch HTML profile with button anchor text
    clutch_html = """
    <html><body>
      <a href="https://www.clutch-saas.com">Visit Website</a>
    </body></html>
    """
    
    profile_li = extractor.extract_from_html(linkedin_html, "https://www.linkedin.com/company/pythondeveloper", "1.0.0")
    profile_cl = extractor.extract_from_html(clutch_html, "https://clutch.co/profile/clutch-saas", "1.0.0")
    
    assert profile_li.website == "https://pybuddy.com"
    assert profile_li.website_source == "linkedin"
    
    assert profile_cl.website == "https://www.clutch-saas.com"
    assert profile_cl.website_source == "clutch"


def test_rejection_analytics_updates_across_stages():
    clear_rejections()
    
    record_rejection("search_ignored_by_rule")
    record_rejection("semantic_low_score")
    record_rejection("validator_rule_violation:missing website")
    record_rejection("cleaner_flagged:sparse_no_contact_channel")
    record_rejection("verifier_failed")
    
    rejections_file = "data/rejection_stats.json"
    assert os.path.exists(rejections_file)
    
    with open(rejections_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    assert data["search_ignored_by_rule"] == 1
    assert data["semantic_low_score"] == 1
    assert data["validator_rule_violation:missing website"] == 1
    assert data["cleaner_flagged:sparse_no_contact_channel"] == 1
    assert data["verifier_failed"] == 1


@patch("discovery.homepage_evaluator._fetch_homepage")
def test_accepted_snippet_triggers_quick_crawl(mock_fetch):
    mock_fetch.return_value = "<html><body><h1>Hello World</h1></body></html>"
    
    # Set up cache miss
    url = "https://www.linkedin.com/company/saas-fast-miss"
    # Ensure cache is clear
    set_cached_company(url, CompanyProfile(ontology_version="1.0.0"))
    
    # We clear the cached entry to simulate a cache miss
    from semantic.semantic_cache import _company_cache
    cache_key = _get_company_cache_key(url)
    if cache_key in _company_cache:
         del _company_cache[cache_key]

    ranker = SemanticRanker()
    intent = IntentProfile(primary_domain="ai", concepts={"python", "ai"})
    
    with patch("discovery.semantic_ranking_engine.get_cached_intent", return_value=intent):
        # Trigger quick crawl via discovery step
        from discovery.company_discovery import discover_companies
        
        # Mock search provider return values
        mock_result = {
            "title": "SaaS Fast - LinkedIn",
            "snippet": "Find python resources, articles and learn new things about AI",
            "url": url
        }
        
        import config
        orig_bonus = getattr(config, "LITERAL_MATCH_BONUS", 40)
        config.LITERAL_MATCH_BONUS = 0
        try:
            with patch("discovery.company_discovery.run_search", return_value=[mock_result]):
                with patch("discovery.company_discovery.guess_company_name", return_value="SaaS Fast"):
                    results = discover_companies("saas")
        finally:
            config.LITERAL_MATCH_BONUS = orig_bonus
                
                # Check that _fetch_homepage was triggered due to cache miss
                assert mock_fetch.called


def test_query_budget_limit():
    import config
    from query.dork_generator import generate_search_tasks
    
    # Temporarily set budget to 5 for test stability
    orig_budget = getattr(config, "MAX_QUERIES_BUDGET", 20)
    config.MAX_QUERIES_BUDGET = 5
    
    try:
        tasks = list(generate_search_tasks("python Noida"))
        assert len(tasks) <= 5
        assert len(tasks) > 0
    finally:
        config.MAX_QUERIES_BUDGET = orig_budget


def test_dynamic_concept_ranking():
    from semantic.ontology_manager import OntologyManager
    from query.expansion import record_query_outcome, _QUERY_FEEDBACK, _QUERY_FEEDBACK_LOCK
    
    om = OntologyManager()
    
    # Backup existing feedback to be hermetic
    with _QUERY_FEEDBACK_LOCK:
        backup = dict(_QUERY_FEEDBACK)
        _QUERY_FEEDBACK.clear()
        
        # Inject high ROI score for "Django" concept in query feedback
        # OntologyManager normalizes concepts to Title Case, so seeds use Title Case too
        _QUERY_FEEDBACK["Django development company"] = {
            "score": 50.0,
            "queries_run": 5,
            "leads_found": 5
        }
        _QUERY_FEEDBACK["Flask backend services"] = {
            "score": -10.0,
            "queries_run": 5,
            "leads_found": 0
        }
        
    try:
        ranked = om.get_ranked_concepts("software_development", "python", top_n=3)
        assert len(ranked) > 0
        # "Django" should rank high due to high historical score injection
        # OntologyManager returns Title Case concepts
        assert "Django" in ranked or "Django" == ranked[0]
    finally:
        with _QUERY_FEEDBACK_LOCK:
            _QUERY_FEEDBACK.clear()
            _QUERY_FEEDBACK.update(backup)


def test_source_discovery_score():
    from query.expansion import record_query_outcome, get_source_discovery_score, _QUERY_FEEDBACK, _QUERY_FEEDBACK_LOCK
    
    # Clean previous source entry
    with _QUERY_FEEDBACK_LOCK:
        if "source:brave" in _QUERY_FEEDBACK:
            del _QUERY_FEEDBACK["source:brave"]
            
    record_query_outcome("test query", "accepted_company", provider="brave")
    record_query_outcome("test query 2", "zero_result", provider="brave") # -1
    
    score = get_source_discovery_score("brave")
    # points: accepted (+5) + zero (-1) = 4 points total / 2 runs = 2.0 avg score
    assert score == 2.0


def test_query_type_diversity():
    from query.query_planner import QueryPlanner
    from query.expansion import _QUERY_FEEDBACK, _QUERY_FEEDBACK_LOCK
    
    # Backup and clear feedback so dynamic concepts don't get pushed out of top_n=3
    with _QUERY_FEEDBACK_LOCK:
        backup = dict(_QUERY_FEEDBACK)
        _QUERY_FEEDBACK.clear()
        
    try:
        planner = QueryPlanner()
        tasks = planner.plan_queries("python Noida")
        queries = [t.query.lower() for t in tasks]
        
        # 1. Tech family
        assert any("django" in q or "fastapi" in q for q in queries)
        # 2. Service family
        assert any("services" in q or "consulting" in q or "outsourcing" in q for q in queries)
        # 3. Location family
        assert any("noida" in q for q in queries)
        # 4. LinkedIn unquoted
        assert any("site:linkedin.com/company python noida" in q for q in queries)
    finally:
        with _QUERY_FEEDBACK_LOCK:
            _QUERY_FEEDBACK.clear()
            _QUERY_FEEDBACK.update(backup)


def test_software_development_domain_resolves():
    from semantic.semantic_intent_resolver import SemanticIntentResolver
    resolver = SemanticIntentResolver()
    
    intent = resolver.resolve("python")
    assert intent.primary_domain.lower() == "software_development"


def test_no_exclusion_operators_in_queries():
    """Regression: -site: exclusions caused VALID_ZERO_RESULTS on Google.
    
    All exclusion operators were removed in the query planner refactor.
    This test ensures they never creep back in.
    """
    from query.query_planner import QueryPlanner

    planner = QueryPlanner()
    tasks = planner.plan_queries("python noida")

    for task in tasks:
        assert "-site:" not in task.query, (
            f"Query contains -site: exclusion operator: '{task.query}'"
        )


def test_directory_list_routes_to_extractor():
    """Regression: DIRECTORY_LIST pages must route to the directory mining
    queue rather than being fed into the semantic scorer.

    Verifies that classify_result returns DIRECTORY_LIST for known directory
    URLs, and that should_ignore_result allows them through (so the routing
    branch in the search loop can intercept them).
    """
    from discovery.company_discovery import classify_result, should_ignore_result

    directory_urls = [
        {"url": "https://clutch.co/directory/python-developers", "title": "Top Python Developers"},
        {"url": "https://goodfirms.co/companies/python", "title": "Best Python Companies"},
        {"url": "https://crunchbase.com/discover/organization.companies", "title": "Companies"},
    ]

    for result in directory_urls:
        classification, reason = classify_result(result)
        assert classification == "DIRECTORY_LIST", (
            f"Expected DIRECTORY_LIST for {result['url']}, got {classification} ({reason})"
        )

        # should_ignore_result must NOT reject DIRECTORY_LIST results —
        # the routing branch in discover_companies handles them.
        # Note: Crunchbase is hard-coded to return True (ignored) in should_ignore_result.
        if "crunchbase.com" not in result["url"]:
            result_copy = dict(result)
            assert should_ignore_result(result_copy) is False, (
                f"should_ignore_result rejected DIRECTORY_LIST page: {result['url']}"
            )
            assert result_copy.get("classification") == "DIRECTORY_LIST"


def test_article_bypasses_semantic_scorer():
    """Regression: ARTICLE, BLOG, and NEWS pages must be rejected by the
    page-type gate (should_ignore_result) before they ever reach the
    semantic scorer.

    This prevents wasting semantic scorer budget on non-company content.
    """
    from discovery.company_discovery import should_ignore_result, classify_result

    non_company_results = [
        {"url": "https://en.wikipedia.org/wiki/Python_(programming_language)", "title": "Python - Wikipedia"},
        {"url": "https://techcrunch.com/2024/01/15/python-companies-to-watch/", "title": "Python Companies to Watch"},
        {"url": "https://medium.com/@someone/python-frameworks-guide-2024", "title": "Python Frameworks Guide 2024"},
        {"url": "https://www.example.com/blog/python-development-tips", "title": "Python Development Tips"},
    ]

    for result in non_company_results:
        classification, reason = classify_result(result)
        assert classification == "REJECT", (
            f"Expected REJECT for {result['url']}, got {classification} ({reason})"
        )

        ignored = should_ignore_result(dict(result))
        assert ignored is True, (
            f"should_ignore_result allowed non-company page through: {result['url']}"
        )
