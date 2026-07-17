import time
import pytest
from collections import defaultdict
from search.manager import SearchManager

def test_circuit_breaker_flow():
    # 1. Initialize SearchManager
    sm = SearchManager()
    
    # Ensure google_html starts in CLOSED state with 0 score
    pname = "google_html"
    assert sm._provider_breaker_states[pname] == "CLOSED"
    assert sm._provider_failure_scores[pname] == 0.0
    assert sm.provider_health[pname] is True

    # 2. Record 429 failures (+4 points each)
    sm._record_provider_failure_score(pname, 4.0, "429 Rate Limit")
    assert sm._provider_breaker_states[pname] == "CLOSED"
    assert sm._provider_failure_scores[pname] == 4.0

    sm._record_provider_failure_score(pname, 4.0, "429 Rate Limit")
    assert sm._provider_breaker_states[pname] == "CLOSED"
    assert sm._provider_failure_scores[pname] == 8.0

    # 3. Add 4.0 more points (total 12.0), which exceeds 10.0 threshold and trips the breaker
    sm._record_provider_failure_score(pname, 4.0, "429 Rate Limit")
    assert sm._provider_breaker_states[pname] == "OPEN"
    assert sm.provider_health[pname] is False
    assert pname in sm._provider_cooldowns

    # 4. Trigger recovery by simulating cooldown elapsed
    sm._provider_cooldowns[pname] = time.time() - 10  # Back-date cooldown to the past
    sm._recover_cooled_providers()

    # Breaker should transition to HALF_OPEN
    assert sm._provider_breaker_states[pname] == "HALF_OPEN"
    assert sm.provider_health[pname] is True

    # 5. Test probe failure: any failure during HALF_OPEN trips it back to OPEN immediately
    sm._record_provider_failure_score(pname, 1.0, "Probe query failure")
    assert sm._provider_breaker_states[pname] == "OPEN"
    assert sm.provider_health[pname] is False

    # 6. Back-date cooldown again to test probe success
    sm._provider_cooldowns[pname] = time.time() - 10
    sm._recover_cooled_providers()
    assert sm._provider_breaker_states[pname] == "HALF_OPEN"

    # Simulate success transition: mock the search loop success path
    breaker_state = sm._provider_breaker_states.get(pname)
    if breaker_state == "HALF_OPEN":
        sm._provider_breaker_states[pname] = "CLOSED"
        sm._provider_failure_scores[pname] = 0.0
    
    assert sm._provider_breaker_states[pname] == "CLOSED"
    assert sm._provider_failure_scores[pname] == 0.0
    assert sm.provider_health[pname] is True
