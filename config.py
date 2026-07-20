import os

from dotenv import load_dotenv

load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# Provider selection
# ─────────────────────────────────────────────────────────────────────────────

# "auto" = pick first available; or specify a slug like "serpapi" / "bing"
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "auto").strip().lower()


# Ordered list of providers to try (env: comma-separated string)
# Free providers first, paid rescue provider (BrightData) last.
# BrightData only fires after free engines fail, return zero, or hit rate limits.
_raw_priority   = os.getenv("SEARCH_PROVIDER_PRIORITY", "google_html,duckduckgo,brave,bing,brightdata")
SEARCH_PROVIDER_PRIORITY: list[str] = [p.strip() for p in _raw_priority.split(",") if p.strip()]

# ─────────────────────────────────────────────────────────────────────────────
# Provider connection policy
# ─────────────────────────────────────────────────────────────────────────────
# proxy_only   → always route through proxy pool (Google needs this)
# direct_first → try direct IP; on failure (timeout/403/429), retry via proxy
PROVIDER_CONNECTION_POLICY: dict[str, str] = {
    "google_html":       "proxy_only",
    "bing":              "proxy_only",
    "duckduckgo":        "direct_first",
    "brave":             "direct_first",
    "directory_provider": "direct_first",
    "repository_provider": "direct_first",
}

GOOGLE_MAX_CONCURRENT = int(os.getenv("GOOGLE_MAX_CONCURRENT", "2"))

# ─────────────────────────────────────────────────────────────────────────────
# Provider enable / disable flags
# ─────────────────────────────────────────────────────────────────────────────

ENABLE_SERPAPI          = os.getenv("ENABLE_SERPAPI",          "true").lower()  == "true"
ENABLE_GOOGLE_CSE       = os.getenv("ENABLE_GOOGLE_CSE",       "true").lower()  == "true"
#ENABLE_CUSTOM_PROVIDER  = os.getenv("ENABLE_CUSTOM_PROVIDER",  "false").lower() == "true"
ENABLE_GOOGLE_HTML      = os.getenv("ENABLE_GOOGLE_HTML",      "false").lower() == "true"  # experimental
ENABLE_BING             = os.getenv("ENABLE_BING",             "true").lower()  == "true"



# SerpAPI
SERPAPI_KEY             = os.getenv("SERPAPI_KEY", "")

# Bright Data
ENABLE_BRIGHTDATA       = os.getenv("ENABLE_BRIGHTDATA",       "true").lower()  == "true"
BRIGHTDATA_KEY          = os.getenv("BRIGHTDATA_KEY", "")
BRIGHTDATA_ZONE         = os.getenv("BRIGHTDATA_ZONE", "serp_api1")

# Google Custom Search Engine
GOOGLE_CSE_KEY          = os.getenv("GOOGLE_CSE_KEY", "")
GOOGLE_CSE_CX           = os.getenv("GOOGLE_CSE_CX", "")

# Generic / custom REST provider
CUSTOM_PROVIDER_URL     = os.getenv("CUSTOM_PROVIDER_URL", "")
CUSTOM_PROVIDER_KEY     = os.getenv("CUSTOM_PROVIDER_KEY", "")


# ─────────────────────────────────────────────────────────────────────────────
# Search tuning
# ─────────────────────────────────────────────────────────────────────────────

MAX_RESULTS_PER_QUERY   = int(os.getenv("MAX_RESULTS_PER_QUERY",  "10"))
GOOGLE_MIN_RESULTS      = int(os.getenv("GOOGLE_MIN_RESULTS",     "3"))

GLOBAL_QUERY_LIMIT      = int(os.getenv("GLOBAL_QUERY_LIMIT",     "50"))

# Legacy alias — kept for any code that still references MAX_COMPANIES_PER_QUERY
MAX_COMPANIES_PER_QUERY = MAX_RESULTS_PER_QUERY


# ─────────────────────────────────────────────────────────────────────────────
# Network / retry
# ─────────────────────────────────────────────────────────────────────────────

MAX_RETRIES             = int(os.getenv("MAX_RETRIES",    "3"))
REQUEST_DELAY           = int(os.getenv("REQUEST_DELAY",  "2"))
REQUEST_TIMEOUT         = int(os.getenv("REQUEST_TIMEOUT","10"))

# Google Scheduler Settings
GOOGLE_MAX_CONCURRENT   = int(os.getenv("GOOGLE_MAX_CONCURRENT",   "2"))
GOOGLE_REQUEST_BUDGET   = int(os.getenv("GOOGLE_REQUEST_BUDGET",   "6"))
GOOGLE_DELAY_MIN        = float(os.getenv("GOOGLE_DELAY_MIN",      "2.0"))
GOOGLE_DELAY_MAX        = float(os.getenv("GOOGLE_DELAY_MAX",      "6.0"))
GOOGLE_CAPTCHA_COOLDOWN = float(os.getenv("GOOGLE_CAPTCHA_COOLDOWN", "1800.0"))
GOOGLE_429_COOLDOWN     = float(os.getenv("GOOGLE_429_COOLDOWN",     "900.0"))
GOOGLE_PROXY_SCORE_THRESHOLD = float(os.getenv("GOOGLE_PROXY_SCORE_THRESHOLD", "10.0"))

GOOGLE_CB_WINDOW_SIZE = int(os.getenv("GOOGLE_CB_WINDOW_SIZE", "20"))
GOOGLE_CB_FAIL_THRESHOLD = float(os.getenv("GOOGLE_CB_FAIL_THRESHOLD", "0.8"))
GOOGLE_CB_MIN_SAMPLES = int(os.getenv("GOOGLE_CB_MIN_SAMPLES", "6"))
GOOGLE_CB_OPEN_SECONDS = int(os.getenv("GOOGLE_CB_OPEN_SECONDS", "60"))


# Search Cache Settings
CACHE_ENABLED          = os.getenv("CACHE_ENABLED", os.getenv("ENABLE_SEARCH_CACHE", "True")).lower() == "true"
ENABLE_SEARCH_CACHE    = CACHE_ENABLED
SEARCH_CACHE_TTL       = int(os.getenv("SEARCH_CACHE_TTL", "86400"))
SEARCH_CACHE_FILE      = os.getenv("SEARCH_CACHE_FILE", "search_cache.json")
SEARCH_CACHE_NAMESPACE = os.getenv("SEARCH_CACHE_NAMESPACE", "default").strip() or "default"
CACHE_ZERO_RESULTS     = os.getenv("CACHE_ZERO_RESULTS", "False").lower() == "true"
FORCE_LIVE_SEARCH      = os.getenv("FORCE_LIVE_SEARCH", "False").lower() == "true"
GOOGLE_MAX_PROXY_RETRIES = int(os.getenv("GOOGLE_MAX_PROXY_RETRIES", "5"))
GOOGLE_FAILURE_CACHE_TTL = int(os.getenv("GOOGLE_FAILURE_CACHE_TTL", "600"))

# Query expansion weights. Higher values are tried earlier.
QUERY_EXPANSION_WEIGHTS = {
    "generic": float(os.getenv("QUERY_EXPANSION_WEIGHT_GENERIC", "1.0")),
    "quoted": float(os.getenv("QUERY_EXPANSION_WEIGHT_QUOTED", "0.95")),
    "source_specific": float(os.getenv("QUERY_EXPANSION_WEIGHT_SOURCE_SPECIFIC", "0.65")),
}

# Adaptive Reuse Intervals (seconds)
MIN_REUSE_INTERVALS = {
    "google": 15.0,
    "bing": 3.0,
    "default": 0.0
}




# ─────────────────────────────────────────────────────────────────────────────
# Discovery expansion
# ─────────────────────────────────────────────────────────────────────────────

# Stop paginating when this many valid companies have been collected.
TARGET_COMPANIES        = int(os.getenv("TARGET_COMPANIES",   "50"))
# Stop discovery when we have this many high-confidence ('ALLOW') companies.
TARGET_HIGH_CONFIDENCE  = int(os.getenv("TARGET_HIGH_CONFIDENCE", "10"))
# Base runtime threshold (seconds) before stopping query loops.
MAX_RUNTIME             = int(os.getenv("MAX_RUNTIME", "120"))
# SRE relevance thresholds
RELEVANCE_THRESHOLD_LOW = int(os.getenv("RELEVANCE_THRESHOLD_LOW", "30"))
RELEVANCE_THRESHOLD_MEDIUM = int(os.getenv("RELEVANCE_THRESHOLD_MEDIUM", "60"))
RELEVANCE_THRESHOLD_HIGH = int(os.getenv("RELEVANCE_THRESHOLD_HIGH", "80"))
# Maximum search-result pages to fetch per query (pagination depth).
MAX_SEARCH_PAGES        = int(os.getenv("MAX_SEARCH_PAGES",   "3"))
# Number of parallel workers for website extraction + contact discovery.
MAX_CRAWL_WORKERS       = int(os.getenv("MAX_CRAWL_WORKERS",  "5"))
# Number of parallel workers for directory candidates evaluation.
DISCOVERY_PARALLEL_WORKERS = int(os.getenv("DISCOVERY_PARALLEL_WORKERS", "5"))
# Maximum candidate profile pages (Clutch/GoodFirms links) to crawl/evaluate per run.
MAX_DIRECTORY_CANDIDATES_TO_EVALUATE = int(os.getenv("MAX_DIRECTORY_CANDIDATES_TO_EVALUATE", "50"))


# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_FOLDER           = "output"                             # root — don't write files here directly
RAW_OUTPUT_FOLDER       = os.path.join(OUTPUT_FOLDER, "raw")   # Pillar 1 lead cards land here
DATA_FOLDER             = "data"



# Old code used SEARCH_ENGINE — map it to SEARCH_PROVIDER so nothing breaks.
SEARCH_ENGINE = SEARCH_PROVIDER

# Configurable Cache Key Strategy for directory/platform domains
CACHE_KEY_STRATEGY = {
    "linkedin.com": "url",
    "clutch.co": "url",
    "goodfirms.co": "url",
    "github.com": "url",
    "yellowpages.com": "url",
    "indiamart.com": "url",
    "justdial.com": "url",
    "*": "domain"
}

# Enforced query budget (physical search queries limit)
MAX_QUERIES_BUDGET = int(os.getenv("MAX_QUERIES_BUDGET", "20"))

# Brave Search settings
ENABLE_BRAVE = os.getenv("ENABLE_BRAVE", "true").lower() == "true"
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")

