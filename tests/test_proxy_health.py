"""Quick smoke tests for the proxy health module."""
import time
from collections import deque
from network_client_project.network.proxy_health import (
    OutcomeType, GoogleTier,
    freshness_factor, aging_decay, compute_google_tier,
    compute_google_confidence, combined_confidence,
    recent_success_ratio, avg_latency, compute_derived_score,
    quarantine_duration, DerivedScoreCache,
)
from network_client_project.network.proxy_manager import Proxy

def test_freshness_decay():
    now = time.time()
    assert freshness_factor(now) == 1.0,           "≤2 min should be 1.0"
    assert freshness_factor(now - 60) == 1.0,      "1 min ago should be 1.0"
    assert freshness_factor(now - 300) == 0.8,     "5 min ago should be 0.8"
    assert freshness_factor(now - 1200) == 0.5,    "20 min ago should be 0.5"
    assert freshness_factor(now - 2400) == 0.2,    "40 min ago should be 0.2"
    assert freshness_factor(now - 7200) == 0.0,    "2 hours ago should be 0.0"
    assert freshness_factor(None) == 0.0,           "None should be 0.0"
    print("✅ freshness_decay passed")

def test_aging_decay():
    score = aging_decay(100.0, time.time())
    assert abs(score - 100.0) < 0.01, f"Just used → should be ~100, got {score}"
    
    one_week_ago = time.time() - 7 * 86400
    score = aging_decay(100.0, one_week_ago)
    expected = 100.0 * (0.995 ** 7)
    assert abs(score - expected) < 0.01, f"7 days → expected {expected:.2f}, got {score:.2f}"
    
    score_none = aging_decay(100.0, None)
    assert abs(score_none - 50.0) < 0.01, f"None → expected 50.0, got {score_none}"
    print("✅ aging_decay passed")

def test_google_tier():
    history = deque(maxlen=50)
    # No data → Tier E
    assert compute_google_tier(history) == GoogleTier.E, "Empty should be Tier E"
    
    # 15 SERPs out of 20 → 75% → Tier A
    now = time.time()
    for i in range(15):
        history.append((now - i, OutcomeType.GOOGLE_SERP))
    for i in range(5):
        history.append((now - 15 - i, OutcomeType.GOOGLE_CAPTCHA))
    assert compute_google_tier(history) == GoogleTier.A, "75% SERP should be Tier A"
    
    # Reset: 10 SERPs, 10 CAPTCHAs → 50% → Tier B
    history.clear()
    for i in range(10):
        history.append((now - i, OutcomeType.GOOGLE_SERP))
    for i in range(10):
        history.append((now - 10 - i, OutcomeType.GOOGLE_CAPTCHA))
    assert compute_google_tier(history) == GoogleTier.B, "50% SERP should be Tier B"
    
    # Reset: 2 SERPs, 18 timeouts → 10% → Tier C
    history.clear()
    for i in range(2):
        history.append((now - i, OutcomeType.GOOGLE_SERP))
    for i in range(18):
        history.append((now - 2 - i, OutcomeType.GOOGLE_TIMEOUT))
    assert compute_google_tier(history) == GoogleTier.C, "10% SERP + timeouts should be Tier C"
    print("✅ google_tier passed")

def test_quarantine_backoff():
    assert quarantine_duration(0) == 60.0,   "Step 0 → 60s"
    assert quarantine_duration(1) == 120.0,  "Step 1 → 120s"
    assert quarantine_duration(2) == 300.0,  "Step 2 → 300s"
    assert quarantine_duration(3) == 600.0,  "Step 3 → 600s"
    assert quarantine_duration(4) == 600.0,  "Step 4 → 600s (capped)"
    assert quarantine_duration(99) == 600.0, "Step 99 → 600s (capped)"
    print("✅ quarantine_backoff passed")

def test_confidence():
    history = deque(maxlen=50)
    now = time.time()
    # No outcomes → None
    assert compute_google_confidence(history) is None
    
    # 8 SERPs, 2 CAPTCHAs (< MIN_OBS=10 but has data)
    for i in range(8):
        history.append((now - i, OutcomeType.GOOGLE_SERP))
    for i in range(2):
        history.append((now - 8 - i, OutcomeType.GOOGLE_CAPTCHA))
    conf = compute_google_confidence(history)
    assert conf is not None
    expected = (8 + 1) / (10 + 2)  # Beta(1,1) prior → 9/12 = 0.75
    assert abs(conf - expected) < 0.01, f"Expected {expected:.3f}, got {conf:.3f}"
    print("✅ confidence passed")

def test_combined_confidence():
    # With enough observations, confidence dominates
    result = combined_confidence(0.8, 50.0, 15, max_score=100.0)
    assert abs(result - 0.8) < 0.01, f"Expected 0.8, got {result}"
    
    # With 5 observations out of 10 minimum, 50/50 blend
    result = combined_confidence(0.8, 50.0, 5, max_score=100.0)
    expected = 0.8 * 0.5 + 0.5 * 0.5  # 0.4 + 0.25 = 0.65
    assert abs(result - expected) < 0.01, f"Expected {expected}, got {result}"
    
    # With None confidence, use proxy_score
    result = combined_confidence(None, 80.0, 0, max_score=100.0)
    assert abs(result - 0.8) < 0.01
    print("✅ combined_confidence passed")

def test_derived_score_cache():
    cache = DerivedScoreCache()
    assert cache.get("proxy1") is None
    cache.put("proxy1", 0.75)
    assert abs(cache.get("proxy1") - 0.75) < 0.01
    cache.invalidate("proxy1")
    assert cache.get("proxy1") is None
    print("✅ derived_score_cache passed")

def test_proxy_outcome_recording():
    p = Proxy(raw_url="test:1234")
    assert p.last_success_ts is None
    assert len(p.outcome_history) == 0
    
    # Record success
    p.record_success(domain="www.google.com", reason="VALID_RESULTS", latency_s=1.5)
    assert p.last_success_ts is not None
    assert len(p.outcome_history) == 1
    assert p.outcome_history[0][1] == OutcomeType.GOOGLE_SERP
    assert len(p.latency_samples) == 1
    assert abs(p.latency_samples[0] - 1.5) < 0.01
    
    # Record failure
    p.record_failure(domain="www.google.com", reason="CAPTCHA", latency_s=2.0)
    assert p.last_failure_ts is not None
    assert len(p.outcome_history) == 2
    assert p.outcome_history[1][1] == OutcomeType.GOOGLE_CAPTCHA
    assert p.quarantine_until is not None  # Should be quarantined
    print("✅ proxy_outcome_recording passed")

def test_proxy_tier_and_derived():
    p = Proxy(raw_url="test:5678")
    # No history → Tier E
    assert p.get_google_tier() == GoogleTier.E
    
    # Add 15 SERP outcomes
    now = time.time()
    for i in range(15):
        p.outcome_history.append((now - i, OutcomeType.GOOGLE_SERP))
    p.last_success_ts = now
    p.last_used = now
    
    assert p.get_google_tier() == GoogleTier.A
    
    dscore = p.get_derived_score()
    assert dscore > 0, f"Derived score should be positive, got {dscore}"
    print(f"  Derived score for Tier A proxy: {dscore:.4f}")
    print("✅ proxy_tier_and_derived passed")

if __name__ == "__main__":
    test_freshness_decay()
    test_aging_decay()
    test_google_tier()
    test_quarantine_backoff()
    test_confidence()
    test_combined_confidence()
    test_derived_score_cache()
    test_proxy_outcome_recording()
    test_proxy_tier_and_derived()
    print("\n🎉 All tests passed!")
