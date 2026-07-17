import os
import json
import re
import time
import math
from abc import ABC, abstractmethod

import utils.stats_tracker as stats
from semantic.semantic_profile import IntentProfile, CompanyProfile
from semantic.ontology_manager import OntologyManager, ONTOLOGY_VERSION
from semantic.semantic_intent_resolver import SemanticIntentResolver
from semantic.company_semantic_extractor import CompanySemanticExtractor
from semantic.semantic_matcher import WeightedMatcher, load_semantic_weights
from semantic.semantic_cache import get_cached_intent, set_cached_intent, get_cached_company, set_cached_company

# ---------- Legacy / Online Weights Learning Wrapper ----------

_batch_feedback = []

def record_feedback(action: str, matched_signals: list[str]) -> None:
    """Queue weight learning feedback logs."""
    _batch_feedback.append((action, matched_signals))

def apply_batch_learning() -> None:
    """Save batch feedback logs to JSON weights exactly once at end-of-run."""
    if not _batch_feedback:
        return

    weights = load_semantic_weights()
    for action, signals in _batch_feedback:
        for sig in signals:
            key = _signal_to_key(sig)
            if key in weights:
                if action == "reward":
                    weights[key] = min(50.0, weights[key] + 0.5)
                elif action == "penalize":
                    weights[key] = max(1.0, weights[key] - 0.5)

    path = "data/semantic_weights.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(weights, f, indent=2, ensure_ascii=False)
        print("[SemanticRankingEngine] Configured B2B semantic weights updated.")
    except Exception as e:
        print(f"[SemanticRankingEngine] Error saving weights: {e}")
        
    _batch_feedback.clear()

def _signal_to_key(signal_name: str) -> str:
    mapping = {
        "Description": "description",
        "Services": "services",
        "Technologies": "technologies",
        "Products": "products",
        "Positions": "positions",
        "Blog/Articles": "blog"
    }
    return mapping.get(signal_name, "")

# ---------- Ranking Base Class ----------

class BaseRanker(ABC):
    @abstractmethod
    def score_snippet(self, title: str, snippet: str, keyword: str, url: str = "") -> dict:
        """Evaluate snippet-level relevance score."""
        pass

    @abstractmethod
    def score_html(self, html: str, keyword: str, snippet_res: dict, url: str = "") -> dict:
        """Evaluate HTML-level deep relevance score."""
        pass

# ---------- SemanticRanker Subclass Implementation ----------

class SemanticRanker(BaseRanker):
    def __init__(self):
        self.om = OntologyManager()
        self.resolver = SemanticIntentResolver(self.om)
        self.extractor = CompanySemanticExtractor()
        self.matcher = WeightedMatcher()

    def detect_industry(self, text: str) -> str:
        if not text:
            return "Unknown"
        text_lower = text.lower()
        scores = {}
        for domain, channels in self.om.ontology.items():
            count = 0.0
            matched_unique = set()
            
            for term in channels.get("concepts", []):
                matches = len(re.findall(r'\b' + re.escape(term.lower()) + r'\b', text_lower))
                if matches > 0:
                    count += 2.0 * matches
                    matched_unique.add(term.lower())
            for term in channels.get("products", []):
                matches = len(re.findall(r'\b' + re.escape(term.lower()) + r'\b', text_lower))
                if matches > 0:
                    count += 1.5 * matches
                    matched_unique.add(term.lower())
            for term in channels.get("services", []):
                matches = len(re.findall(r'\b' + re.escape(term.lower()) + r'\b', text_lower))
                if matches > 0:
                    count += 1.5 * matches
                    matched_unique.add(term.lower())
            for term in channels.get("positions", []):
                matches = len(re.findall(r'\b' + re.escape(term.lower()) + r'\b', text_lower))
                if matches > 0:
                    count += 1.0 * matches
                    matched_unique.add(term.lower())
                    
            if count > 0:
                total_terms = (
                    len(channels.get("concepts", [])) +
                    len(channels.get("products", [])) +
                    len(channels.get("services", [])) +
                    len(channels.get("positions", []))
                )
                # Normalize using square root of domain ontology size to balance specificity vs coverage
                scores[domain] = count / math.sqrt(max(1, total_terms))
                
        if not scores:
            return "Unknown"
        return max(scores, key=scores.get).title()

    def get_tier(self, score: int) -> str:
        if score >= 80:
            return "HIGH"
        elif score >= 60:
            return "MEDIUM"
        elif score >= 40:
            return "LOW"
        else:
            return "REJECT"

    def score_snippet(self, title: str, snippet: str, keyword: str, url: str = "") -> dict:
        # 1. Resolve IntentProfile
        t0 = time.time()
        intent = get_cached_intent(keyword)
        if not intent:
            intent = self.resolver.resolve(keyword)
            set_cached_intent(keyword, intent)
        t_res_ms = (time.time() - t0) * 1000.0
        stats.increment("time_intent_resolver_ms", int(t_res_ms))
        stats.increment("count_intent_resolver")

        # 2. Extract snippet-level CompanyProfile
        t0 = time.time()
        company = self.extractor.extract_from_snippet(title, snippet, url, self.om.version)
        t_ext_ms = (time.time() - t0) * 1000.0
        stats.increment("time_company_extractor_ms", int(t_ext_ms))
        stats.increment("count_company_extractor")
        
        # 3. Match profiles
        t0 = time.time()
        res = self.matcher.match(intent, company)
        t_match_ms = (time.time() - t0) * 1000.0
        stats.increment("time_semantic_matcher_ms", int(t_match_ms))
        stats.increment("count_semantic_matcher")
        
        return {
            "score": res["score"],
            "tier": self.get_tier(res["score"]),
            "matched_signals": res["matched_signals"],
            "rejected_signals": res["rejected_signals"],
            "score_breakdown": res["score_breakdown"],
            "industry": self.detect_industry(title + " " + snippet),
            "confidence": res["confidence"],
            "aborted": False,
            "company_type": res["company_type"],
            "semantic_trace": res["semantic_trace"],
            "technologies": [t["value"] for t in company.technologies],
            "products": [p["value"] for p in company.products],
            "website": getattr(company, "website", ""),
            "website_source": getattr(company, "website_source", "")
        }

    def score_html(self, html: str, keyword: str, snippet_res: dict, url: str = "") -> dict:
        # 1. Resolve IntentProfile
        t0 = time.time()
        intent = get_cached_intent(keyword)
        if not intent:
            intent = self.resolver.resolve(keyword)
            set_cached_intent(keyword, intent)
        t_res_ms = (time.time() - t0) * 1000.0
        stats.increment("time_intent_resolver_ms", int(t_res_ms))
        stats.increment("count_intent_resolver")

        # 2. Extract or Cache CompanyProfile
        t0 = time.time()
        company = None
        if url:
            company = get_cached_company(url)

        if not company:
            company = self.extractor.extract_from_html(html, url, self.om.version, intent.concepts)
            if url:
                set_cached_company(url, company)
        t_ext_ms = (time.time() - t0) * 1000.0
        stats.increment("time_company_extractor_ms", int(t_ext_ms))
        stats.increment("count_company_extractor")

        # 3. Match profiles
        t0 = time.time()
        res = self.matcher.match(intent, company)
        t_match_ms = (time.time() - t0) * 1000.0
        stats.increment("time_semantic_matcher_ms", int(t_match_ms))
        stats.increment("count_semantic_matcher")

        clean_profile_text = (
            (company.description.get("value", "") if isinstance(company.description, dict) else str(company.description or "")) + " " +
            company.sections.get("homepage", "") + " " +
            company.sections.get("about", "") + " " +
            company.sections.get("services", "")
        )

        return {
            "score": res["score"],
            "tier": self.get_tier(res["score"]),
            "matched_signals": res["matched_signals"],
            "rejected_signals": res["rejected_signals"],
            "score_breakdown": res["score_breakdown"],
            "industry": self.detect_industry(clean_profile_text),
            "confidence": res["confidence"],
            "aborted": False,
            "company_type": res["company_type"],
            "semantic_trace": res["semantic_trace"],
            "technologies": [t["value"] for t in company.technologies],
            "products": [p["value"] for p in company.products],
            "website": getattr(company, "website", ""),
            "website_source": getattr(company, "website_source", "")
        }
