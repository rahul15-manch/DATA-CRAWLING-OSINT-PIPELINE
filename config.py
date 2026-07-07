"""
config.py
=========
Pillar 1 — all configuration read from environment / .env file.

Search Provider Keys
--------------------
SEARCH_PROVIDER
    "auto"        — pick the first available provider in priority list
    "serpapi"     — use SerpAPI exclusively (failover still applies)
    "bing"        — use Bing exclusively
    etc.

SEARCH_PROVIDER_PRIORITY
    Comma-separated ordered list.  SearchManager tries providers
    left-to-right.  Change this via .env without touching code.
    Default: "serpapi,google_cse,generic_api,bing"
"""

import os
from dotenv import load_dotenv

load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# Provider selection
# ─────────────────────────────────────────────────────────────────────────────

# "auto" = pick first available; or specify a slug like "serpapi" / "bing"
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "auto").strip().lower()

# Ordered list of providers to try (env: comma-separated string)
_raw_priority   = os.getenv("SEARCH_PROVIDER_PRIORITY", "serpapi,google_cse,generic_api,bing")
SEARCH_PROVIDER_PRIORITY: list[str] = [p.strip() for p in _raw_priority.split(",") if p.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Provider enable / disable flags
# ─────────────────────────────────────────────────────────────────────────────

ENABLE_SERPAPI          = os.getenv("ENABLE_SERPAPI",          "true").lower()  == "true"
ENABLE_GOOGLE_CSE       = os.getenv("ENABLE_GOOGLE_CSE",       "true").lower()  == "true"
ENABLE_CUSTOM_PROVIDER  = os.getenv("ENABLE_CUSTOM_PROVIDER",  "false").lower() == "true"
ENABLE_GOOGLE_HTML      = os.getenv("ENABLE_GOOGLE_HTML",      "false").lower() == "true"  # experimental
ENABLE_BING             = os.getenv("ENABLE_BING",             "true").lower()  == "true"


# ─────────────────────────────────────────────────────────────────────────────
# API Credentials
# ─────────────────────────────────────────────────────────────────────────────

# SerpAPI
SERPAPI_KEY             = os.getenv("SERPAPI_KEY", "")

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

# Legacy alias — kept for any code that still references MAX_COMPANIES_PER_QUERY
MAX_COMPANIES_PER_QUERY = MAX_RESULTS_PER_QUERY


# ─────────────────────────────────────────────────────────────────────────────
# Network / retry
# ─────────────────────────────────────────────────────────────────────────────

MAX_RETRIES             = int(os.getenv("MAX_RETRIES",    "3"))
REQUEST_DELAY           = int(os.getenv("REQUEST_DELAY",  "2"))
REQUEST_TIMEOUT         = int(os.getenv("REQUEST_TIMEOUT","10"))


# ─────────────────────────────────────────────────────────────────────────────
# Discovery expansion
# ─────────────────────────────────────────────────────────────────────────────

# Stop paginating when this many valid companies have been collected.
TARGET_COMPANIES        = int(os.getenv("TARGET_COMPANIES",   "50"))
# Maximum search-result pages to fetch per query (pagination depth).
MAX_SEARCH_PAGES        = int(os.getenv("MAX_SEARCH_PAGES",   "3"))
# Number of parallel workers for website extraction + contact discovery.
MAX_CRAWL_WORKERS       = int(os.getenv("MAX_CRAWL_WORKERS",  "5"))


# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_FOLDER           = "output"
DATA_FOLDER             = "data"


# ─────────────────────────────────────────────────────────────────────────────
# Legacy aliases
# ─────────────────────────────────────────────────────────────────────────────

# Old code used SEARCH_ENGINE — map it to SEARCH_PROVIDER so nothing breaks.
SEARCH_ENGINE = SEARCH_PROVIDER
