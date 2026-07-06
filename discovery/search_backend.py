"""
Shared search backend wrapper, used by both company_discovery and
contact_discovery. Supports SerpAPI (recommended) and googlesearch
(free, local testing only).
"""

import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def search_serpapi(query: str, max_results: int = 10) -> list:
    from serpapi import GoogleSearch

    if not config.SERPAPI_KEY:
        raise ValueError("SERPAPI_KEY not set. Export it as an environment variable.")

    params = {
        "q": query,
        "num": max_results,
        "api_key": config.SERPAPI_KEY,
    }
    search = GoogleSearch(params)
    results = search.get_dict()

    organic = results.get("organic_results", [])
    return [
        {
            "title": r.get("title"),
            "url": r.get("link"),
            "snippet": r.get("snippet"),
        }
        for r in organic
    ]


from googlesearch import search

def search_googlesearch(query, max_results=10):

    print("=" * 50)
    print("QUERY :", query)
    print("=" * 50)

    results = list(
        search(
            query,
            num_results=max_results
        )
    )

    print(results)

    return [
        {
            "title": None,
            "url": url,
            "snippet": None
        }
        for url in results
    ]

def run_search(query: str, max_results: int = None) -> list:
    """
    Runs a single query against the configured backend, with retries.
    Returns a list of raw result dicts: {title, url, snippet}.
    """
    max_results = max_results or config.MAX_COMPANIES_PER_QUERY

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            if config.SEARCH_ENGINE == "serpapi":
                return search_serpapi(query, max_results)
            elif config.SEARCH_ENGINE == "googlesearch":
                return search_googlesearch(query, max_results)
            else:
                raise ValueError(f"Unknown SEARCH_ENGINE: {config.SEARCH_ENGINE}")
        except Exception as e:
            print(f"[search] attempt {attempt} failed for query '{query}': {e}")
            time.sleep(config.REQUEST_DELAY * attempt)

    print(f"[search] all retries failed for query: {query}")
    return []
