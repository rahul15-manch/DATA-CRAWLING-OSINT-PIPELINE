"""
query/query_roi_tracker.py
===========================
Tracks template ROI yield (unique leads / execution count) across runs.
Enforces a minimum sample threshold (10 runs) before adjusting template weights,
preventing overreactions to single lucky or unlucky runs.
"""

import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger("pillar1.query.roi_tracker")

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "query_roi_state.json")

class QueryRoiTracker:
    def __init__(self, min_sample_threshold: int = 10):
        self.min_sample_threshold = min_sample_threshold
        self.stats: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    self.stats = json.load(f)
        except Exception as e:
            logger.warning(f"[QueryRoiTracker] Failed to load ROI state: {e}")
            self.stats = {}

    def save(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            logger.warning(f"[QueryRoiTracker] Failed to save ROI state: {e}")

    def record_query_outcome(self, template_str: str, leads_yielded: int):
        if template_str not in self.stats:
            self.stats[template_str] = {"runs": 0, "total_leads": 0, "weight": 1.0}
        
        entry = self.stats[template_str]
        entry["runs"] += 1
        entry["total_leads"] += leads_yielded
        
        # Only update weight after minimum sample threshold is reached
        if entry["runs"] >= self.min_sample_threshold:
            avg_yield = entry["total_leads"] / float(entry["runs"])
            if avg_yield > 2.0:
                entry["weight"] = 1.5  # High ROI
            elif avg_yield > 0.5:
                entry["weight"] = 1.0  # Moderate ROI
            else:
                entry["weight"] = 0.5  # Low ROI
                
        self.save()

    def record_provider_yield(self, provider_name: str, industry: str, leads_yielded: int):
        key = f"provider:{provider_name}:{industry.lower()}"
        if key not in self.stats:
            self.stats[key] = {"runs": 0, "total_leads": 0, "weight": 1.0}
        
        entry = self.stats[key]
        entry["runs"] += 1
        entry["total_leads"] += leads_yielded
        if entry["runs"] >= self.min_sample_threshold:
            avg = entry["total_leads"] / float(entry["runs"])
            entry["weight"] = 1.5 if avg > 2.0 else (1.0 if avg > 0.5 else 0.5)
        self.save()

    def get_best_provider_for_industry(self, industry: str, default: str = "google_html") -> str:
        prefix = f"provider:"
        suffix = f":{industry.lower()}"
        candidates = []
        for key, entry in self.stats.items():
            if key.startswith(prefix) and key.endswith(suffix):
                provider = key[len(prefix):-len(suffix)]
                weight = entry.get("weight", 1.0)
                candidates.append((provider, weight))
        if not candidates:
            return default
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

query_roi_tracker = QueryRoiTracker()

