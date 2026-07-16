"""
query/expansion.py
==================
Shared helpers for layered query expansion.

The query layer builds semantic intent variants first, then applies source
operators and adaptive weights. This keeps the broad search intent visible
to generic providers while still generating source-specific dorks where
appropriate.
"""

from __future__ import annotations

import threading
import logging
from collections import defaultdict

import config
from query.intent_classifier import classify_intent, expand_to_company_keywords

logger = logging.getLogger(__name__)
_QUERY_FEEDBACK_LOCK = threading.Lock()
_QUERY_FEEDBACK: dict[str, dict[str, int | float]] = defaultdict(
    lambda: {"success": 0, "zero": 0, "parser": 0, "unavailable": 0, "failures": 0, "last_updated": 0.0}
)

# Removed _GENERIC_BUSINESS_SUFFIXES to prevent repetitive query spam


def _normalize_query_key(query: str) -> str:
    return " ".join(query.lower().split())


import json
import os
import re

_FEEDBACK_FILE = os.path.join("data", "query_feedback.json")


def _load_query_feedback():
    global _QUERY_FEEDBACK
    if os.path.exists(_FEEDBACK_FILE):
        try:
            with open(_FEEDBACK_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                with _QUERY_FEEDBACK_LOCK:
                    _QUERY_FEEDBACK.clear()
                    for k, v in data.items():
                        _QUERY_FEEDBACK[k] = v
            logger.info(f"Loaded persistent query feedback from {_FEEDBACK_FILE}")
        except Exception as e:
            logger.error(f"Failed to load query feedback: {e}")


def _save_query_feedback():
    try:
        os.makedirs(os.path.dirname(_FEEDBACK_FILE), exist_ok=True)
        with _QUERY_FEEDBACK_LOCK:
            data = {k: dict(v) for k, v in _QUERY_FEEDBACK.items()}
        with open(_FEEDBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save query feedback: {e}")


def find_matching_template(query: str) -> str | None:
    from query.company_template import COMPANY_TEMPLATES
    q_norm = query.lower().strip()
    
    for src_dict in COMPANY_TEMPLATES:
        templates = src_dict["templates"]
        for template in templates:
            pattern = re.escape(template)
            pattern = pattern.replace(r"\{\keyword\}", r".+")
            pattern = "^" + pattern + ".*$"
            if re.match(pattern, q_norm):
                return template
    return None


def build_semantic_company_variants(keyword: str) -> list[str]:
    """Return ordered semantic variants before source-specific operators."""

    raw = (keyword or "").strip()
    if not raw:
        return []

    intent = classify_intent(raw)
    variants: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        candidate = candidate.strip()
        if not candidate:
            return
            
        import re
        # Prevent "company company" or "software company company"
        candidate = re.sub(r'(?i)\bcompany\s+company\b', 'company', candidate)
        candidate = re.sub(r'(?i)\bcompanies\s+company\b', 'companies', candidate)
        candidate = re.sub(r'(?i)\bfirm\s+firm\b', 'firm', candidate)
        candidate = re.sub(r'(?i)\bstartup\s+startup\b', 'startup', candidate)
        candidate = candidate.strip()
            
        # Near-duplicate filter (e.g. skip "software companies" if "software company" is seen)
        cand_norm = candidate.lower().replace("companies", "company").replace("firms", "firm")
        if cand_norm.endswith('s') and not cand_norm.endswith('ss'):
            cand_norm = cand_norm[:-1]
            
        for s in seen:
            s_norm = s.lower().replace("companies", "company").replace("firms", "firm")
            if s_norm.endswith('s') and not s_norm.endswith('ss'):
                s_norm = s_norm[:-1]
            if cand_norm == s_norm:
                return  # Skip near-duplicate
                
        seen.add(candidate)
        variants.append(candidate)

    # Keep the original keyword as the broadest seed.
    add(raw)

    for expansion in expand_to_company_keywords(raw):
        add(expansion)

    return variants[:5]


def get_query_base_weight(query: str) -> float:
    """Return a configurable base weight for a candidate query."""

    weights = getattr(config, "QUERY_EXPANSION_WEIGHTS", {}) or {}
    q_lower = query.lower()

    if "site:" in q_lower:
        return float(weights.get("source_specific", 0.65))
    if q_lower.startswith('"'):
        return float(weights.get("quoted", 0.95))
    return float(weights.get("generic", 1.0))


def record_query_outcome(
    query: str,
    outcome: str,
    result_count: int = 0,
) -> None:
    """Store lightweight feedback and template ROI."""
    key = _normalize_query_key(query)
    if not key:
        return

    import time
    with _QUERY_FEEDBACK_LOCK:
        stats = _QUERY_FEEDBACK[key]
        now = time.time()
        stats["last_updated"] = now
        
        if outcome == "success" and result_count > 0:
            stats["success"] += 1
            stats["leads_found"] = stats.get("leads_found", 0) + result_count
            stats["failures"] = 0  # Reset consecutive failures on success
        elif outcome == "zero_result":
            stats["zero"] += 1
            stats["failures"] = stats.get("failures", 0) + 1
        elif outcome == "parser_failure":
            stats["parser"] += 1
        elif outcome == "unavailable":
            stats["unavailable"] += 1
            
        stats["queries_run"] = stats.get("queries_run", 0) + 1

        # Track template-level ROI
        template = find_matching_template(query)
        if template:
            t_stats = _QUERY_FEEDBACK.setdefault(f"template:{template}", {
                "queries_run": 0, "leads_found": 0, "success": 0, "zero": 0, "parser": 0, "unavailable": 0, "last_updated": now, "failures": 0
            })
            t_stats["last_updated"] = now
            t_stats["queries_run"] += 1
            if outcome == "success" and result_count > 0:
                t_stats["leads_found"] += result_count
                t_stats["success"] += 1
                t_stats["failures"] = 0
            elif outcome == "zero_result":
                t_stats["zero"] += 1
                t_stats["failures"] = t_stats.get("failures", 0) + 1
            elif outcome == "parser_failure":
                t_stats["parser"] += 1
            elif outcome == "unavailable":
                t_stats["unavailable"] += 1

    _save_query_feedback()


def get_query_feedback_weight(query: str) -> float:
    """Return a multiplicative weight derived from historical template ROI."""
    template = find_matching_template(query)
    if not template:
        return 1.0

    import time
    with _QUERY_FEEDBACK_LOCK:
        # Negative query learning (exact query check)
        q_key = _normalize_query_key(query)
        q_stats = _QUERY_FEEDBACK.get(q_key)
        if q_stats:
            fails = q_stats.get("failures", 0)
            if fails >= 30:
                # Exponential decay: recover weight over time
                days = (time.time() - q_stats.get("last_updated", time.time())) / 86400.0
                decay = math.exp(-0.02 * days) # ~2% recovery per day
                penalty = 0.999 * decay # Max penalty 0.999, decays towards 0
                return max(0.001, 1.0 - penalty)

        # Template ROI check
        t_stats = _QUERY_FEEDBACK.get(f"template:{template}")
        if not t_stats:
            return 1.0

        q_run = t_stats.get("queries_run", 0)
        l_found = t_stats.get("leads_found", 0)
        if q_run <= 0:
            return 1.0
            
        t_fails = t_stats.get("failures", 0)
        if t_fails >= 50:
             days = (time.time() - t_stats.get("last_updated", time.time())) / 86400.0
             decay = math.exp(-0.02 * days)
             penalty = 0.999 * decay
             return max(0.001, 1.0 - penalty)

        # Calculate template ROI: average leads found per query
        roi = l_found / q_run
        # Scale the weight based on ROI (min 0.2, max 2.0)
        weight = max(0.2, min(2.0, roi))
        return weight


def rank_query_candidate(query: str) -> float:
    """Combine static weights with live feedback for ranking."""

    return get_query_base_weight(query) * get_query_feedback_weight(query)


def get_query_feedback_snapshot() -> dict[str, dict[str, int]]:
    """Return a copy of the in-memory template feedback table."""

    with _QUERY_FEEDBACK_LOCK:
        return {key: dict(value) for key, value in _QUERY_FEEDBACK.items()}

# Load query feedback on startup
_load_query_feedback()
