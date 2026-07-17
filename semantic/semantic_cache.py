"""
semantic/semantic_cache.py
==========================
Disk-backed semantic caching for IntentProfile and CompanyProfile.
Invalidates on TTL (30 days) or ontology version mismatch.
"""

import os
import json
import time
from semantic.semantic_profile import IntentProfile, CompanyProfile
from semantic.ontology_manager import ONTOLOGY_VERSION
import utils.stats_tracker as stats

# ---------- Paths & Memory Store ----------

INTENT_CACHE_PATH = "data/semantic_intent_cache.json"
COMPANY_CACHE_PATH = "data/semantic_company_cache.json"

_intent_cache = {}
_company_cache = {}

# ---------- IO Load/Save Helpers ----------

def load_caches():
    global _intent_cache, _company_cache
    if os.path.exists(INTENT_CACHE_PATH):
        try:
            with open(INTENT_CACHE_PATH, "r", encoding="utf-8") as f:
                _intent_cache = json.load(f)
        except Exception:
            _intent_cache = {}
    else:
        _intent_cache = {}
        
    if os.path.exists(COMPANY_CACHE_PATH):
        try:
            with open(COMPANY_CACHE_PATH, "r", encoding="utf-8") as f:
                _company_cache = json.load(f)
        except Exception:
            _company_cache = {}
    else:
        _company_cache = {}

def save_caches():
    os.makedirs("data", exist_ok=True)
    try:
        with open(INTENT_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_intent_cache, f, indent=2, ensure_ascii=False)
        with open(COMPANY_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_company_cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[SemanticCache] Error saving cache: {e}")

# ---------- Public Get/Set API ----------

def get_cached_intent(keyword: str) -> IntentProfile | None:
    kw_key = keyword.lower().strip()
    if kw_key in _intent_cache:
        entry = _intent_cache[kw_key]
        if entry.get("ontology_version") == ONTOLOGY_VERSION:
            stats.increment("intent_cache_hits")
            return IntentProfile.from_dict(entry["intent_profile"])
            
    stats.increment("intent_cache_misses")
    return None

def set_cached_intent(keyword: str, intent: IntentProfile):
    kw_key = keyword.lower().strip()
    _intent_cache[kw_key] = {
        "ontology_version": ONTOLOGY_VERSION,
        "intent_profile": intent.to_dict()
    }
    save_caches()

def _get_company_cache_key(url_or_domain: str) -> str:
    if not url_or_domain:
        return ""
    val_clean = url_or_domain.lower().strip()
    if val_clean.startswith("http"):
        from urllib.parse import urlparse
        domain = urlparse(val_clean).netloc.lower()
        # Canonicalize: strip leading www.
        if domain.startswith("www."):
            domain = domain[4:]
    else:
        domain = val_clean
        if domain.startswith("www."):
            domain = domain[4:]

    import config
    strategy = "domain"
    for pattern, strat in getattr(config, "CACHE_KEY_STRATEGY", {}).items():
        if pattern != "*" and pattern in domain:
            strategy = strat
            break

    if strategy == "url" and val_clean.startswith("http"):
        return val_clean.rstrip("/")
    return domain


def get_cached_company(url_or_domain: str) -> CompanyProfile | None:
    cache_key = _get_company_cache_key(url_or_domain)
    if not cache_key:
        return None

    if cache_key in _company_cache:
        entry = _company_cache[cache_key]
        # Invalidate if ontology version changed
        if entry.get("ontology_version") != ONTOLOGY_VERSION:
            return None
            
        # Check TTL (30 days)
        last_crawled_ts = entry.get("timestamp", 0.0)
        if time.time() - last_crawled_ts > 30 * 86400:
            return None
            
        stats.increment("company_cache_hits")
        return CompanyProfile.from_dict(entry["company_profile"])
        
    stats.increment("company_cache_misses")
    return None

def set_cached_company(url_or_domain: str, company: CompanyProfile):
    cache_key = _get_company_cache_key(url_or_domain)
    if not cache_key:
        return
    _company_cache[cache_key] = {
        "ontology_version": ONTOLOGY_VERSION,
        "timestamp": time.time(),
        "company_profile": company.to_dict()
    }
    save_caches()

# Auto-load caches on import
load_caches()
