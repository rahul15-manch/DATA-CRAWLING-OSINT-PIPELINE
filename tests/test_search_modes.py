import pytest
import os
import config
from config import SearchMode
from query.query_planner import QueryPlanner
from discovery.semantic_ranking_engine import SemanticRanker
from discovery.homepage_evaluator import evaluate_homepage
from semantic.semantic_cache import INTENT_CACHE_PATH, COMPANY_CACHE_PATH, _intent_cache, _company_cache, get_cached_intent, set_cached_intent
from semantic.semantic_profile import IntentProfile

@pytest.fixture(autouse=True)
def clear_caches():
    _intent_cache.clear()
    _company_cache.clear()
    if os.path.exists(INTENT_CACHE_PATH):
        try:
            os.remove(INTENT_CACHE_PATH)
        except Exception:
            pass
    if os.path.exists(COMPANY_CACHE_PATH):
        try:
            os.remove(COMPANY_CACHE_PATH)
        except Exception:
            pass


def test_query_planner_hybrid_mode():
    config.SEARCH_MODE = SearchMode.HYBRID
    planner = QueryPlanner()
    tasks = planner.plan_queries("python Noida")
    
    queries = [t.query.lower() for t in tasks]
    
    # In hybrid mode, we expect BOTH literal exact queries and semantic queries to be present
    assert any("site:linkedin.com/company python noida" in q for q in queries)
    assert any("custom python development noida" in q for q in queries)


def test_advanced_token_matching_variations():
    ranker = SemanticRanker()
    
    # 1. Plural / Suffix variations: Technology / Technologies
    company_1 = {"name": "ABC Technologies Ltd"}
    assert ranker._is_literal_match(company_1, "technology")
    assert ranker._is_literal_match(company_1, "technologies")
    
    # 2. Punctuation removal: Technology®
    company_2 = {"name": "Ultimate Technology® Inc"}
    assert ranker._is_literal_match(company_2, "technology")
    
    # 3. Hyphenated / compound variations: technology-based / technology-driven
    company_3 = {"name": "technology-based systems"}
    assert ranker._is_literal_match(company_3, "technology")
    
    # 4. Short form roots: tech -> technology
    company_4 = {"name": "Clean Tech Corp"}
    assert ranker._is_literal_match(company_4, "technology")
    assert ranker._is_literal_match(company_4, "tech")


def test_literal_match_bonus_and_overrides():
    # Set config to exact mode and matching bonus to 30
    config.SEARCH_MODE = SearchMode.EXACT
    config.LITERAL_MATCH_BONUS = 30
    ranker = SemanticRanker()
    
    # Match candidate with literal keyword should get base score + 30 bonus
    res_match = ranker.score_snippet(
        title="ABC Automation Ltd",
        snippet="Specializing in PLC programming and industrial control systems.",
        keyword="automation"
    )
    # The base score of automation B2B matching is > 0, so final score should reflect bonus
    assert res_match["score"] >= 30
    assert res_match["tier"] != "REJECT"

    # Reject candidate without literal keyword
    res_reject = ranker.score_snippet(
        title="Ace Services Ltd",
        snippet="Leading B2B IT provider",
        keyword="python"
    )
    assert res_reject["score"] == 0
    assert res_reject["tier"] == "REJECT"


def test_evaluate_homepage_exact_mode_checks():
    # If matching in EXACT mode, evaluate_homepage must reject ONLY if keyword absent in Name, Metadata, and Homepage text
    html_content = "<html><head><title>Engineering Tomorrow</title></head><body>AI Automation Solutions<p>Contact: info@engineering.com</p><a href='/about'>About</a><a href='/services'>Services</a></body></html>"
    
    # Case 1: Exact mode, matching keyword is not present in Title/Body -> REJECT
    assert evaluate_homepage(html_content, keyword="technology", mode="exact") == "REJECT"
    
    # Case 2: Exact mode, matching keyword present in body text -> ALLOW/LIKELY_COMPANY
    assert evaluate_homepage(html_content, keyword="automation", mode="exact") != "REJECT"


def test_mode_partitioned_intent_cache():
    # Set to EXACT and cache an intent
    config.SEARCH_MODE = SearchMode.EXACT
    intent = IntentProfile(primary_domain="software", concepts={"python"}, confidence=1.0)
    set_cached_intent("python", intent)
    
    # Verify EXACT key can hit
    assert get_cached_intent("python") is not None
    
    # Switch to SEMANTIC and verify cache miss (since it is partitioned)
    config.SEARCH_MODE = SearchMode.SEMANTIC
    assert get_cached_intent("python") is None

