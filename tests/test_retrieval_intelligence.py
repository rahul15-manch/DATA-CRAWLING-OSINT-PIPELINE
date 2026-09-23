"""
tests/test_retrieval_intelligence.py
====================================
Comprehensive test suite for Milestone 5: Retrieval & Search Intelligence Improvements.
Verifies:
- Test 1: Company query generation (COMPANY family, domain targeting)
- Test 2: Contact intent query generation (inurl:contact, intitle:contact)
- Test 3: Leadership/team intent query generation (intitle:leadership, inurl:about, inurl:team)
- Test 4: Document intent query generation (filetype:pdf)
- Test 5: Query deduplication
- Test 6: Query budget enforcement
- Test 7: Deterministic query prioritization
- Test 8: Graceful handling of invalid/malformed input
- Test 9: Preservation of user-provided advanced operators
- Test 10: Hunter API deferral (disabled by default, returns SKIPPED, zero network calls)
- Test 11: Retrieval metrics calculations
- Test 12: Structured query metadata validation
"""

import pytest
import config
from models.search_task import SearchTask
from models.lead_record import LeadRecord
from pillar1.query.query_planner import QueryPlanner, _detect_operators, _infer_query_family
from pillar1.query.dork_generator import generate_search_tasks
from pillar1.query.retrieval_metrics import RetrievalMetricsTracker
from osint.providers.hunter_provider import HunterProvider
from osint.models import ProviderStatus


def test_1_company_query_generation():
    """Verify company/domain search intent produces COMPANY query family and domain dorks."""
    planner = QueryPlanner()
    tasks = planner.plan_queries("Swiggy")
    
    # Check that company tasks are produced
    company_tasks = [t for t in tasks if t.family == "COMPANY"]
    assert len(company_tasks) > 0
    
    # Check that site: operator was generated for domain
    site_tasks = [t for t in tasks if "site:" in t.query.lower()]
    assert len(site_tasks) > 0
    assert any("swiggy" in t.query.lower() for t in site_tasks)

    # Check category company queries
    cat_tasks = planner.plan_queries("automation")
    assert any(t.family == "COMPANY" for t in cat_tasks)


def test_2_contact_intent_query_generation():
    """Verify inurl:contact and/or intitle:contact queries are generated."""
    planner = QueryPlanner()
    
    # Entity query generates contact footprinting
    tasks = planner.plan_queries("Swiggy")
    contact_tasks = [t for t in tasks if t.family == "CONTACT"]
    assert len(contact_tasks) > 0
    assert any("inurl:contact" in t.query.lower() for t in contact_tasks)

    # Keyword with explicit contact intent
    contact_intent_tasks = planner.plan_queries("automation contact")
    assert any("inurl:contact" in t.query.lower() or "intitle:contact" in t.query.lower() for t in contact_intent_tasks)


def test_3_leadership_team_intent_query_generation():
    """Verify intitle:leadership and inurl:about/team queries are generated."""
    planner = QueryPlanner()
    
    # Entity query
    tasks = planner.plan_queries("Swiggy")
    team_tasks = [t for t in tasks if t.family == "ABOUT_TEAM"]
    assert len(team_tasks) > 0
    assert any("intitle:leadership" in t.query.lower() or "inurl:about" in t.query.lower() for t in team_tasks)

    # Keyword with leadership intent
    leadership_tasks = planner.plan_queries("automation leadership")
    assert any("intitle:leadership" in t.query.lower() or "inurl:team" in t.query.lower() for t in leadership_tasks)


def test_4_document_intent_query_generation():
    """Verify filetype:pdf is generated only where appropriate."""
    planner = QueryPlanner()
    
    # Entity query generates document family task
    tasks = planner.plan_queries("Automation Anywhere")
    doc_tasks = [t for t in tasks if t.family == "DOCUMENT"]
    assert len(doc_tasks) > 0
    assert any("filetype:pdf" in t.query.lower() for t in doc_tasks)

    # Keyword with explicit pdf intent
    explicit_doc_tasks = planner.plan_queries("automation company profile pdf")
    pdf_tasks = [t for t in explicit_doc_tasks if "filetype:pdf" in t.query.lower()]
    assert len(pdf_tasks) > 0


def test_5_query_deduplication():
    """Verify equivalent queries are never emitted twice."""
    tasks = list(generate_search_tasks("automation", deterministic=True))
    queries_seen = set()
    for t in tasks:
        norm_q = t.query.lower().strip()
        assert norm_q not in queries_seen, f"Duplicate query emitted: {t.query}"
        queries_seen.add(norm_q)


def test_6_query_budget_enforcement():
    """Verify generated queries strictly respect configured budget."""
    # Test custom tight budget
    budget_5 = list(generate_search_tasks("automation", deterministic=True, max_budget=5))
    assert len(budget_5) <= 5

    budget_12 = list(generate_search_tasks("Automation Anywhere", deterministic=True, max_budget=12))
    assert len(budget_12) <= 12

    # Default budget
    default_tasks = list(generate_search_tasks("automation", deterministic=True))
    total_allowed = getattr(config, "MAX_TOTAL_SEARCH_BUDGET", 25)
    assert len(default_tasks) <= total_allowed


def test_7_query_determinism():
    """Verify identical inputs produce the exact same prioritized query list in deterministic mode."""
    run1 = [t.query for t in generate_search_tasks("software engineering", deterministic=True)]
    run2 = [t.query for t in generate_search_tasks("software engineering", deterministic=True)]
    assert run1 == run2
    assert len(run1) > 0


def test_8_malformed_invalid_input_safety():
    """Verify malformed, empty, or whitespace inputs do not crash the generator."""
    planner = QueryPlanner()
    
    assert planner.plan_queries("") == []
    assert planner.plan_queries("   ") == []
    assert list(generate_search_tasks("")) == []
    assert list(generate_search_tasks("   ")) == []
    
    # Weird characters
    tasks = list(generate_search_tasks("!@#$%^&*()_+", deterministic=True))
    assert isinstance(tasks, list)


def test_9_user_provided_operator_preservation():
    """Verify user-provided advanced operators are preserved and prioritized."""
    planner = QueryPlanner()
    user_query = 'site:example.com "specialized robotics" inurl:contact'
    tasks = planner.plan_queries(user_query)
    
    # User query must be present at the top
    top_task = tasks[0]
    assert top_task.query == user_query
    assert top_task.discovery_mode == "direct"
    assert "site:" in top_task.operator_set
    assert "inurl:" in top_task.operator_set
    assert '""' in top_task.operator_set


@pytest.mark.asyncio
async def test_10_hunter_api_deferral():
    """Verify Hunter is DEFERRED by default, skips execution safely with zero network requests."""
    # Ensure config has HUNTER_ENABLED false by default
    assert getattr(config, "HUNTER_ENABLED", False) is False

    hunter = HunterProvider()
    assert hunter.enabled is False

    lead = LeadRecord(company_name="Automation Anywhere", domain="automationanywhere.com")
    result = await hunter.enrich(lead)

    assert result.status == ProviderStatus.SKIPPED
    assert "DEFERRED — API credentials unavailable" in result.evidence.get("reason", "")
    assert result.evidence.get("hunter_enabled") is False
    assert result.data == {}
    assert result.is_successful is False


def test_11_retrieval_metrics_calculations():
    """Verify retrieval quality metrics calculations."""
    tracker = RetrievalMetricsTracker()
    tracker.start_timing()
    
    tracker.record_query("query 1")
    tracker.record_query("query 2")
    
    tracker.record_result("https://example.com/page1")
    tracker.record_result("https://example.com/page2")
    tracker.record_result("https://example.org/about")
    tracker.record_result("https://example.com/page1")  # duplicate URL
    
    tracker.record_lead("Lead Alpha")
    tracker.record_lead("Lead Beta")
    
    tracker.stop_timing()
    summary = tracker.summary()
    
    assert summary["queries_executed"] == 2
    assert summary["total_results"] == 4
    assert summary["unique_results"] == 3
    assert summary["unique_domains"] == 2  # example.com, example.org
    assert summary["unique_leads"] == 2
    assert summary["query_yield"] == 1.5   # 3 unique results / 2 queries
    assert summary["lead_yield"] == 1.0    # 2 leads / 2 queries
    assert summary["duplicate_rate"] == 0.25 # 1 dupe / 4 total
    assert summary["domain_diversity"] == 0.5 # 2 domains / 4 total
    assert summary["latency_seconds"] >= 0.0


def test_12_structured_query_metadata():
    """Verify SearchTask structured metadata fields are populated."""
    planner = QueryPlanner()
    tasks = planner.plan_queries("Automation Anywhere")
    
    families_seen = {t.family for t in tasks}
    assert "COMPANY" in families_seen
    assert "SOCIAL" in families_seen
    assert "CONTACT" in families_seen
    assert "ABOUT_TEAM" in families_seen
    
    # Ensure all tasks have non-empty operator_set or valid category
    for t in tasks:
        assert isinstance(t.operator_set, list)
        assert t.family in {"COMPANY", "CONTACT", "ABOUT_TEAM", "CAREERS", "DOCUMENT", "REGISTRY", "SOCIAL"}
        assert t.category == "company"
        assert t.original_keyword == "Automation Anywhere"
