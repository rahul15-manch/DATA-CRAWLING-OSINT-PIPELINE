"""
check_providers.py
==================
Provider readiness diagnostic — run this before the main pipeline.

Usage
-----
    python check_providers.py

Output
------
Shows each provider's status, what config keys are missing,
and exactly what to add to .env to enable it.

Also runs a live search with whichever providers are ready
to confirm results actually come back.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from search.manager import SearchManager

def main():
    print()
    print("=" * 60)
    print("  Flowiz Pillar 1 — Provider Diagnostic")
    print("=" * 60)

    sm = SearchManager()

    # 1. Show readiness for every registered provider
    sm.diagnose()

    # 2. Attempt a live test search with active providers
    print("Running live test search: 'software development company'")
    print("-" * 60)
    results = sm.search("software development company", max_results=3)

    if results:
        print(f"\nLive search: OK — {len(results)} results from [{sm.last_provider_used}]")
        for r in results:
            print(f"  [{r.provider_rank}] {r.url}")
            if r.title:
                print(f"       {r.title[:80]}")
    else:
        print("\nLive search: NO RESULTS — all active providers returned empty.")
        print("Check your internet connection and .env configuration.")

    # 3. Print stats
    sm.print_stats()

if __name__ == "__main__":
    main()
