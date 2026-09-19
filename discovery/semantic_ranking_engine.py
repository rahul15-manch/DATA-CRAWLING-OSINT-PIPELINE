import os
import json
import re
import time
import math
from abc import ABC, abstractmethod

import sys
import utils.stats_tracker as stats

_p1_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pillar1"))
if _p1_path not in sys.path:
    sys.path.insert(0, _p1_path)

try:
    from query.intent_classifier import is_entity_query
except ImportError:
    try:
        from pillar1.query.intent_classifier import is_entity_query
    except ImportError:
        def is_entity_query(k: str) -> bool:
            return bool(k and len(k.split()) <= 3)

try:
    from query.query_planner import LOCATIONS
except ImportError:
    try:
        from pillar1.query.query_planner import LOCATIONS
    except ImportError:
        LOCATIONS = set()

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

    def _normalize_text(self, text: str) -> str:
        if not text:
            return ""
        import unicodedata
        # 1. Unicode Normalize NFKD (strip accents/symbols)
        text = unicodedata.normalize('NFKD', text)
        # 2. Lowercase
        text = text.lower()
        # 3. Remove possessives
        text = re.sub(r"\'s\b|s\'\b", "", text)
        # 4. Remove punctuation/symbols (replace with spaces)
        text = re.sub(r"[^\w\s]", " ", text)
        # 5. Collapse whitespace
        words = text.split()
        
        # 6. Normalize common roots/synonyms to a single standardized form
        roots = {
            "technology": "technolog",
            "technologies": "technolog",
            "tech": "technolog",
            "electronics": "electron",
            "electronic": "electron",
            "python": "python",
            "software": "softwar",
            "hardware": "hardwar",
            "developer": "develop",
            "development": "develop",
            "consulting": "consult",
            "consultancy": "consult",
            "automation": "automat",
            "automated": "automat"
        }
        mapped = [roots.get(w, w) for w in words]
        return " ".join(mapped)

    def _is_literal_match(self, company_data: dict, keyword: str) -> bool:
        if not keyword:
            return True
        
        kw_clean = keyword.lower().strip()
        words = kw_clean.split()
        if len(words) > 1 and words[-1] in LOCATIONS:
            kw_clean = " ".join(words[:-1])

        norm_kw = self._normalize_text(kw_clean)
        if not norm_kw:
            return False

        # Gather target text blocks from all specified fields
        target_blocks = []
        target_blocks.append(company_data.get("name") or "")
        target_blocks.append(company_data.get("website_title") or "")
        target_blocks.append(company_data.get("description") or "")
        target_blocks.append(company_data.get("headline") or "")
        target_blocks.append(company_data.get("about") or "")
        target_blocks.extend(company_data.get("services") or [])
        target_blocks.extend(company_data.get("positions") or [])
        target_blocks.extend(company_data.get("industries") or [])
        target_blocks.extend(company_data.get("technologies") or [])

        # Normalize the targets (which will also apply root synonym standardization)
        normalized_target = " ".join(self._normalize_text(str(b)) for b in target_blocks if b)

        # Check if the normalized keyword (or its first word root) matches
        if norm_kw in normalized_target:
            return True
        first_word = norm_kw.split()[0]
        if first_word in normalized_target:
            return True
            
        return False

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
        
        import config
        from config import SearchMode
        search_mode = getattr(config, "SEARCH_MODE", SearchMode.SEMANTIC)
        
        company_data = {
            "name": title,
            "website_title": title,
            "description": snippet,
            "headline": title,
            "about": "",
            "services": [s.get("value", "") for s in company.services] if hasattr(company, "services") else [],
            "positions": [p.get("value", "") for p in company.positions] if hasattr(company, "positions") else [],
            "industries": company.industries if hasattr(company, "industries") else [],
            "technologies": [t.get("value", "") for t in company.technologies] if hasattr(company, "technologies") else [],
        }
        
        # Derivative detection for entity queries (e.g. "Swiggy Clone Dev")
        is_derivative = False
        is_entity_domain_match = False
        is_entity_path_match = False
        url_domain_token = ""
        kw_entity = keyword.lower().strip()
        try:
            from urllib.parse import urlparse
            kw_words = kw_entity.split()
            if len(kw_words) > 1 and kw_words[-1] in LOCATIONS:
                kw_entity = " ".join(kw_words[:-1])
            if is_entity_query(kw_entity):
                title_snippet_text = f"{title or ''} {snippet or ''}".lower()
                derivative_pattern = r'\b(clone|replica|alternative|alternatives|script|template|app like|apps like|similar to|how to build|build a)\b'
                if re.search(derivative_pattern, title_snippet_text):
                    is_derivative = True

                if url:
                    kw_slug = re.sub(r"[^a-z0-9]", "", kw_entity)
                    url_lower = url.lower()
                    parsed_netloc = urlparse(url_lower).netloc.lstrip("www.")
                    url_domain_token = parsed_netloc.split(".")[0]
                    url_slug = re.sub(r"[^a-z0-9]", "", url_domain_token)
                    url_slug_full = re.sub(r"[^a-z0-9]", "", url_lower)

                    if url_slug and kw_slug and url_slug == kw_slug:
                        is_entity_domain_match = True
                    elif kw_slug and (
                        f"/company/{kw_slug}" in url_lower
                        or f"/company/{kw_slug.replace(' ', '-')}" in url_lower
                        or re.search(r'/company/' + re.escape(kw_slug) + r'(/|\b)', url_lower)
                        or f"company{kw_slug}" in url_slug_full
                    ):
                        is_entity_path_match = True
        except Exception:
            pass

        literal_matched = self._is_literal_match(company_data, keyword)
        score = res["score"]

        # Exact entity identity signals force literal_matched = True (unless derivative)
        if (is_entity_domain_match or is_entity_path_match) and not is_derivative:
            literal_matched = True

        if literal_matched and not is_derivative:
            bonus = getattr(config, "LITERAL_MATCH_BONUS", 40)
            score = min(100, score + bonus)
            stats.increment("literal_matches")
            stats.increment("literal_bonus_applied")
        elif is_derivative:
            score = max(0, score - 20)  # Penalize derivative/clone sites on entity queries
            stats.increment("rejected_literal_matches")
        else:
            stats.increment("rejected_literal_matches")

        # ── Entity Identity Bonus ────────────────────────────────────────────
        # When the search keyword is a bare entity name (e.g. "swiggy") and the
        # result URL's domain or URL path matches the entity name, award a large
        # bonus so the actual company homepage / LinkedIn profile clears threshold.
        entity_identity_bonus = 0
        try:
            kw_entity_bonus = keyword.lower().strip()
            kw_words = kw_entity_bonus.split()
            if len(kw_words) > 1 and kw_words[-1] in LOCATIONS:
                kw_entity_bonus = " ".join(kw_words[:-1])
            
            if is_entity_query(kw_entity_bonus) and url and not is_derivative:
                if is_entity_domain_match:
                    entity_identity_bonus = getattr(config, "ENTITY_IDENTITY_BONUS", 60)
                    print(f"[SemanticRanker] Entity domain identity bonus (+{entity_identity_bonus}) applied: domain='{url_domain_token}', kw='{kw_entity_bonus}'")
                elif is_entity_path_match:
                    entity_identity_bonus = getattr(config, "ENTITY_IDENTITY_BONUS", 60)
                    print(f"[SemanticRanker] Entity URL path identity bonus (+{entity_identity_bonus}) applied: url='{url}', kw='{kw_entity_bonus}'")
                # Title identity match: entity name appears as a whole word in the title
                elif kw_entity_bonus and re.search(r'\b' + re.escape(kw_entity_bonus) + r'\b', (title or "").lower()):
                    entity_identity_bonus = getattr(config, "ENTITY_IDENTITY_BONUS", 60) // 2
                    print(f"[SemanticRanker] Entity title bonus (+{entity_identity_bonus}) applied: title='{(title or '')[:60]}', kw='{kw_entity_bonus}'")
            elif is_derivative:
                print(f"[SemanticRanker] Entity bonus suppressed (derivative detected): title='{(title or '')[:60]}'")
        except Exception:
            pass  # Never let entity detection crash the scorer
            pass  # Never let entity detection crash the scorer
        
        if entity_identity_bonus:
            score = min(100, score + entity_identity_bonus)
            stats.increment("entity_identity_bonuses")

        # ── .ai TLD Discrimination ────────────────────────────────────────────
        # A domain ending in .ai does NOT automatically make a company an AI company.
        # If the keyword is a category query (e.g. "AI") and the result's domain
        # ends in .ai, but there are no corroborating AI signals in the content,
        # remove any score inflation to prevent false positives.
        try:
            from urllib.parse import urlparse as _urlparse
            _tld = url.lower().rsplit(".", 1)[-1].split("/")[0] if url else ""
            if _tld == "ai" and not is_entity_query(keyword):
                _ai_corroborate_terms = {
                    "artificial intelligence", "machine learning", "deep learning",
                    "generative ai", "llm", "neural network", "nlp",
                    "computer vision", "ai company", "ai startup", "ai platform",
                }
                _combined_text = f"{title or ''} {snippet or ''}".lower()
                _has_ai_signal = any(t in _combined_text for t in _ai_corroborate_terms)
                if not _has_ai_signal:
                    # Suppress up to 20 pts of score inflation from .ai TLD alone
                    score = max(0, score - 20)
                    stats.increment("ai_tld_penalty_applied")
        except Exception:
            pass

        tier = self.get_tier(score)

        if search_mode == SearchMode.EXACT and not literal_matched:
            score = 0
            tier = "REJECT"

        return {
            "score": score,
            "tier": tier,
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
            "website_source": getattr(company, "website_source", ""),
            "entity_identity_bonus": entity_identity_bonus,
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

        import config
        from config import SearchMode
        search_mode = getattr(config, "SEARCH_MODE", SearchMode.SEMANTIC)
        
        company_data = {
            "name": company.sections.get("homepage", ""),
            "website_title": company.sections.get("homepage", ""),
            "description": company.description.get("value", "") if isinstance(company.description, dict) else str(company.description or ""),
            "headline": company.sections.get("homepage", ""),
            "about": company.sections.get("about", ""),
            "services": [s.get("value", "") for s in company.services] if hasattr(company, "services") else [],
            "positions": [p.get("value", "") for p in company.positions] if hasattr(company, "positions") else [],
            "industries": company.industries if hasattr(company, "industries") else [],
            "technologies": [t.get("value", "") for t in company.technologies] if hasattr(company, "technologies") else [],
        }
        
        literal_matched = self._is_literal_match(company_data, keyword)
        score = res["score"]
        
        if literal_matched:
            bonus = getattr(config, "LITERAL_MATCH_BONUS", 40)
            score = min(100, score + bonus)
            stats.increment("literal_matches")
            stats.increment("literal_bonus_applied")
        else:
            stats.increment("rejected_literal_matches")
            
        tier = self.get_tier(score)
        
        if search_mode == SearchMode.EXACT and not literal_matched:
            score = 0
            tier = "REJECT"

        clean_profile_text = (
            (company.description.get("value", "") if isinstance(company.description, dict) else str(company.description or "")) + " " +
            company.sections.get("homepage", "") + " " +
            company.sections.get("about", "") + " " +
            company.sections.get("services", "")
        )

        return {
            "score": score,
            "tier": tier,
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
