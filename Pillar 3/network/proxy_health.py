"""
Proxy Health Utilities
─────────────────────
Outcome tracking, freshness decay, aging decay, dynamic Google tier
calculation, derived score computation, and score caching.
"""

import time
import enum
import threading
import logging
from collections import deque
from typing import Optional, List, Tuple, Dict

logger = logging.getLogger(__name__)

# ── Outcome Enum ──────────────────────────────────────────────────────────────

class OutcomeType(str, enum.Enum):
    """Layered outcome categories.
    
    Transport layer:
        TRANSPORT_SUCCESS, TRANSPORT_TIMEOUT, TRANSPORT_TLS_ERROR, TRANSPORT_CONNECTION_ERROR
    Google layer:
        GOOGLE_SERP, GOOGLE_CAPTCHA, GOOGLE_429, GOOGLE_TIMEOUT
    Parser layer:
        PARSER_SUCCESS, PARSER_FAILURE
    """
    # Transport
    TRANSPORT_SUCCESS        = "TRANSPORT_SUCCESS"
    TRANSPORT_TIMEOUT        = "TRANSPORT_TIMEOUT"
    TRANSPORT_TLS_ERROR      = "TRANSPORT_TLS_ERROR"
    TRANSPORT_CONNECTION_ERROR = "TRANSPORT_CONNECTION_ERROR"

    # Google
    GOOGLE_SERP    = "GOOGLE_SERP"
    GOOGLE_CAPTCHA = "GOOGLE_CAPTCHA"
    GOOGLE_429     = "GOOGLE_429"
    GOOGLE_TIMEOUT = "GOOGLE_TIMEOUT"

    # Parser
    PARSER_SUCCESS = "PARSER_SUCCESS"
    PARSER_FAILURE = "PARSER_FAILURE"


# ── Penalty weights per outcome (used in confidence) ──────────────────────────

OUTCOME_WEIGHTS: Dict[OutcomeType, float] = {
    OutcomeType.GOOGLE_SERP:                +1.0,
    OutcomeType.TRANSPORT_SUCCESS:          +0.3,
    OutcomeType.PARSER_SUCCESS:             +0.2,

    OutcomeType.TRANSPORT_TIMEOUT:          -0.1,
    OutcomeType.GOOGLE_TIMEOUT:             -0.2,
    OutcomeType.GOOGLE_429:                 -0.4,
    OutcomeType.GOOGLE_CAPTCHA:             -0.5,
    OutcomeType.TRANSPORT_TLS_ERROR:        -0.8,
    OutcomeType.TRANSPORT_CONNECTION_ERROR:  -1.0,
    OutcomeType.PARSER_FAILURE:             -0.1,
}


# ── Google Tier ───────────────────────────────────────────────────────────────

class GoogleTier(str, enum.Enum):
    """Dynamic tier computed from recent Google outcomes."""
    A = "A"   # Returned SERP recently
    B = "B"   # Connected but CAPTCHA
    C = "C"   # Connected but timeout / 429
    D = "D"   # Transport failure
    E = "E"   # Dead / no data


TIER_PRIORITY = {
    GoogleTier.A: 5,
    GoogleTier.B: 4,
    GoogleTier.C: 3,
    GoogleTier.D: 2,
    GoogleTier.E: 1,
}


# ── Freshness Decay ──────────────────────────────────────────────────────────

def freshness_factor(last_success_ts: Optional[float]) -> float:
    """Gradual freshness decay based on time since last success.
    
    ≤2 min  → 1.0
    ≤10 min → 0.8
    ≤30 min → 0.5
    ≤60 min → 0.2
    >60 min → 0.0
    """
    if not last_success_ts:
        return 0.0
    age = time.time() - last_success_ts
    if age <= 120:
        return 1.0
    if age <= 600:
        return 0.8
    if age <= 1800:
        return 0.5
    if age <= 3600:
        return 0.2
    return 0.0


# ── Proxy Aging Decay ─────────────────────────────────────────────────────────

def aging_decay(proxy_score: float, last_used_ts: Optional[float], decay_base: float = 0.995) -> float:
    """Decay historical proxy_score based on days since last use.
    
    effective_score = proxy_score * (decay_base ** days_unused)
    """
    if not last_used_ts:
        return proxy_score * 0.5  # Unknown age → halve it
    age_days = (time.time() - last_used_ts) / 86400.0
    if age_days <= 0:
        return proxy_score
    return proxy_score * (decay_base ** age_days)


# ── Dynamic Google Tier Calculation ───────────────────────────────────────────

def compute_google_tier(outcome_history: deque) -> GoogleTier:
    """Compute Google tier dynamically from recent outcomes.
    
    Looks at the last 20 Google-related outcomes and classifies.
    """
    google_outcomes = [
        (ts, ot) for ts, ot in outcome_history
        if ot in (
            OutcomeType.GOOGLE_SERP, OutcomeType.GOOGLE_CAPTCHA,
            OutcomeType.GOOGLE_429, OutcomeType.GOOGLE_TIMEOUT
        )
    ]

    if not google_outcomes:
        # Check if we have any transport data
        transport_failures = sum(
            1 for _, ot in outcome_history
            if ot in (OutcomeType.TRANSPORT_CONNECTION_ERROR, OutcomeType.TRANSPORT_TLS_ERROR)
        )
        if transport_failures > 0 and len(outcome_history) > 0:
            ratio = transport_failures / len(outcome_history)
            if ratio > 0.5:
                return GoogleTier.D
        return GoogleTier.E  # No data

    # Take last 20 Google outcomes
    recent = google_outcomes[-20:]
    total = len(recent)

    serp_count    = sum(1 for _, ot in recent if ot == OutcomeType.GOOGLE_SERP)
    captcha_count = sum(1 for _, ot in recent if ot == OutcomeType.GOOGLE_CAPTCHA)
    timeout_count = sum(1 for _, ot in recent if ot in (OutcomeType.GOOGLE_TIMEOUT, OutcomeType.GOOGLE_429))

    serp_ratio = serp_count / total

    if serp_ratio >= 0.7:
        return GoogleTier.A
    if serp_ratio >= 0.4:
        return GoogleTier.B
    if captcha_count + timeout_count > 0:
        return GoogleTier.C
    return GoogleTier.D


# ── Bayesian Google Confidence ────────────────────────────────────────────────

MIN_OBSERVATIONS = 10

def compute_google_confidence(outcome_history: deque) -> Optional[float]:
    """Bayesian confidence from Google outcomes.
    
    Returns None if fewer than MIN_OBSERVATIONS Google outcomes exist.
    Uses a Beta(1,1) prior (uniform).
    """
    google_outcomes = [
        ot for _, ot in outcome_history
        if ot in (
            OutcomeType.GOOGLE_SERP, OutcomeType.GOOGLE_CAPTCHA,
            OutcomeType.GOOGLE_429, OutcomeType.GOOGLE_TIMEOUT
        )
    ]

    total = len(google_outcomes)
    if total == 0:
        return None

    successes = sum(1 for ot in google_outcomes if ot == OutcomeType.GOOGLE_SERP)

    alpha = 1  # prior successes
    beta = 1   # prior failures

    confidence = (successes + alpha) / (total + alpha + beta)

    if total < MIN_OBSERVATIONS:
        return confidence  # Will be blended with proxy_score by caller

    return confidence


def combined_confidence(
    google_confidence: Optional[float],
    proxy_score: float,
    observation_count: int,
    max_score: float = 100.0
) -> float:
    """Combine short-term Google confidence with long-term proxy_score.
    
    When observations < MIN_OBSERVATIONS, confidence weight scales linearly.
    """
    normalized_score = proxy_score / max_score

    if google_confidence is None:
        return normalized_score

    if observation_count >= MIN_OBSERVATIONS:
        return google_confidence
    
    # Gradually blend: confidence takes over as observations grow
    w = observation_count / MIN_OBSERVATIONS
    return google_confidence * w + normalized_score * (1 - w)


# ── Recent Success Ratio ──────────────────────────────────────────────────────

def recent_success_ratio(outcome_history: deque, window_seconds: float = 600.0) -> float:
    """Ratio of successes to total outcomes in the recent time window."""
    now = time.time()
    recent = [(ts, ot) for ts, ot in outcome_history if now - ts <= window_seconds]
    if not recent:
        return 0.0
    successes = sum(
        1 for _, ot in recent
        if ot in (OutcomeType.GOOGLE_SERP, OutcomeType.TRANSPORT_SUCCESS, OutcomeType.PARSER_SUCCESS)
    )
    return successes / len(recent)


# ── Average Latency ──────────────────────────────────────────────────────────

def avg_latency(latency_samples: deque) -> float:
    """Returns the average latency in seconds from the rolling window.
    
    Returns a high default (30s) if no samples exist.
    """
    if not latency_samples:
        return 30.0  # Pessimistic default
    return sum(latency_samples) / len(latency_samples)


# ── Derived Score ─────────────────────────────────────────────────────────────

def compute_derived_score(
    google_confidence: Optional[float],
    proxy_score: float,
    observation_count: int,
    last_success_ts: Optional[float],
    outcome_history: deque,
    latency_samples: deque,
    last_used_ts: Optional[float],
) -> float:
    """Compute the derived scheduling score.
    
    Weights:
        Google confidence: 50%
        Freshness:         25%
        Recent success:    15%
        Latency (inverse): 10%
    """
    # Combined confidence (blends with proxy_score when observations are few)
    conf = combined_confidence(google_confidence, proxy_score, observation_count)

    fresh = freshness_factor(last_success_ts)

    success = recent_success_ratio(outcome_history)

    lat = avg_latency(latency_samples)
    # Inverse latency normalized: 1/lat, capped at 1.0 for very fast proxies
    inv_lat = min(1.0, 1.0 / max(lat, 0.1))

    derived = 0.50 * conf + 0.25 * fresh + 0.15 * success + 0.10 * inv_lat

    # Apply aging decay (reduces the score for long-unused proxies)
    aged_score = aging_decay(proxy_score, last_used_ts)
    aging_factor = aged_score / max(proxy_score, 1.0)
    derived *= max(aging_factor, 0.1)  # Floor at 10% to avoid total zeroing

    return max(derived, 0.001)  # Never return exactly 0 for weighted random


# ── Quarantine Backoff ────────────────────────────────────────────────────────

QUARANTINE_SCHEDULE = [30, 60, 120, 300]  # seconds
QUARANTINE_MAX_STEP = len(QUARANTINE_SCHEDULE) - 1
QUARANTINE_INACTIVE_AFTER = 3  # Mark inactive after this many consecutive backoffs at max

def quarantine_duration(backoff_step: int) -> float:
    """Return quarantine duration for the given backoff step."""
    idx = min(backoff_step, QUARANTINE_MAX_STEP)
    return float(QUARANTINE_SCHEDULE[idx])


# ── Derived Score Cache ───────────────────────────────────────────────────────

class DerivedScoreCache:
    """Caches derived scores per proxy, recomputed every 30s or on invalidation."""

    REFRESH_INTERVAL = 30.0  # seconds

    def __init__(self):
        self._cache: Dict[str, Tuple[float, float]] = {}  # proxy_url → (score, timestamp)
        self._lock = threading.Lock()

    def get(self, proxy_url: str) -> Optional[float]:
        """Get cached score if still fresh."""
        with self._lock:
            entry = self._cache.get(proxy_url)
            if entry is None:
                return None
            score, ts = entry
            if time.time() - ts > self.REFRESH_INTERVAL:
                return None  # Stale
            return score

    def put(self, proxy_url: str, score: float):
        """Cache a newly computed derived score."""
        with self._lock:
            self._cache[proxy_url] = (score, time.time())

    def invalidate(self, proxy_url: str):
        """Invalidate cache for a specific proxy (e.g., after a new outcome)."""
        with self._lock:
            self._cache.pop(proxy_url, None)

    def clear(self):
        with self._lock:
            self._cache.clear()


# Global cache instance
derived_score_cache = DerivedScoreCache()
