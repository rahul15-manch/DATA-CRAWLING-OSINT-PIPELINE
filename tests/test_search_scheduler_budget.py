from __future__ import annotations

import time
import pytest
from utils.budget_manager import ProviderBudgetManager
from utils.deadline import Deadline
from search.manager import SearchManager
from search.exceptions import ProviderUnavailable
from search.result import SearchResult

def test_provider_budget_manager_brightdata():
    bm = ProviderBudgetManager()
    
    # Initialize Deadline
    Deadline.set_timeout(35.0)
    
    # BrightData budget should be dynamically allocated: max(remaining_global, 5.0)
    budget = bm.get_provider_budget("brightdata")
    assert budget >= 5.0

def test_provider_budget_manager_google_fallback():
    bm = ProviderBudgetManager()
    
    # If remaining budget is less than GOOGLE_MIN_FALLBACK_BUDGET (e.g. 18s), google is not allowed
    Deadline.set_timeout(10.0) # remaining is < 18
    assert bm.can_execute("google_html") is False
    
    # If remaining budget is high, google is allowed
    Deadline.set_timeout(30.0)
    assert bm.can_execute("google_html") is True

def test_google_block_cooldown_logic(monkeypatch):
    manager = SearchManager()
    
    # Mock budget manager can_execute to return True
    monkeypatch.setattr(manager.budget_manager, "can_execute", lambda pname: True)
    
    # Initially Google is not disabled
    assert manager._consecutive_blocks["google_html"] == 0
    assert time.time() >= manager._google_disabled_until

    # Mock a provider that throws a permanent block
    class _MockBlockProvider:
        name = "google_html"
        def is_available(self): return True
        def search(self, query, max_results=10, page=0):
            raise ProviderUnavailable("google_html", "ENABLE_JS")

    monkeypatch.setattr(manager, "_get_ordered_providers", lambda: [_MockBlockProvider()])
    
    # Query 1: block -> consecutive_blocks = 1
    manager.search("software developer company 1", max_results=10)
    assert manager._consecutive_blocks["google_html"] == 1
    assert manager._google_disabled_until == 0.0

    # Query 2: block -> consecutive_blocks = 2
    manager.search("software developer company 2", max_results=10)
    assert manager._consecutive_blocks["google_html"] == 2
    
    # Query 3: block -> consecutive_blocks = 3 -> disabled
    manager.search("software developer company 3", max_results=10)
    assert manager._consecutive_blocks["google_html"] == 3
    assert manager._google_disabled_until > time.time()

def test_dynamic_provider_sorting():
    manager = SearchManager()
    
    # Setup stats for two providers:
    # ddg is healthy
    manager.stats["duckduckgo"].queries = 10
    manager.stats["duckduckgo"].failures = 0 # success_rate = 1.0 -> promoted
    
    # google has been failing
    manager.stats["google_html"].queries = 10
    manager.stats["google_html"].failures = 9 # success_rate = 0.1 -> demoted
    
    ordered = manager._get_ordered_providers()
    ordered_names = [p.name for p in ordered]
    
    # Verify ddg is ordered before google_html due to health demotion/promotion
    # DuckDuckGo has success_rate 1.0 (Health > 0.8), Google has success_rate 0.1 (Health < 0.2)
    assert ordered_names.index("duckduckgo") < ordered_names.index("google_html")
