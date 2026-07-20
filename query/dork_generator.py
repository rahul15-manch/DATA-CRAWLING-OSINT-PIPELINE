"""
query/dork_generator.py
=======================
Converts a raw user keyword into a list of SearchTask objects.

This uses an "Intent Expansion" model. Instead of appending static operators
like "site:linkedin.com/company engineering", this expands the intent first:
"engineering" -> ["engineering companies", "engineering firms", ...]
Then it applies the source templates to these expanded intents.

Pipeline
--------
1. Intent Classifier  → detects intent, rewrites job-role / tech keywords
                        into an expanded list of business-intent queries.
2. Source templates   → wraps the expanded queries in source operators.
3. Task generation    → one SearchTask per (source, expanded_query).
"""

from query.company_template import COMPANY_TEMPLATES
from query.expansion import build_semantic_company_variants, rank_query_candidate
from models.search_task import SearchTask

from query.query_planner import QueryPlanner

def generate_search_tasks(keyword: str):
    """
    Generate SearchTask objects for a given keyword using Intent Expansion.

    Parameters
    ----------
    keyword : str
        Raw user input, e.g. "data engineer", "python", "AI startup", "engineering"

    Yields
    ------
    SearchTask
        Ordered search tasks, highest-priority first.
        Category is always "company" — person discovery is Pillar 2.
    """
    keyword = keyword.strip()
    if not keyword:
        return

    planner = QueryPlanner()
    tasks = list(planner.plan_queries(keyword))
    
    import random
    import config
    scored_tasks = []
    for idx, t in enumerate(tasks):
        # Exploration logic: 15% chance to treat query with a high baseline exploration weight (e.g. 1.0)
        # to prevent starvation of low-performing or new queries.
        if random.random() < 0.15:
            weight = 1.0 + (1.0 / (idx + 1.0)) # slightly prefer original planned order
        else:
            weight = rank_query_candidate(t.query)
        scored_tasks.append((weight, idx, t))
        
    # Sort tasks descending by weight
    scored_tasks.sort(key=lambda x: (-x[0], x[1]))
    
    # Enforce budget limit
    budget = getattr(config, "MAX_QUERIES_BUDGET", 20)
    for _, _, task in scored_tasks[:budget]:
        yield task


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _collapse_repeated_words(query: str) -> str:
    """
    Remove consecutively repeated words from a query string.

    Examples
    --------
    "data engineering company company"  →  "data engineering company"
    "python software company company"   →  "python software company"
    "AI startup startup"                →  "AI startup"
    """
    import string
    words  = query.split()
    result = [words[0]] if words else []
    for word in words[1:]:
        clean_prev = result[-1].lower().strip(string.punctuation)
        clean_curr = word.lower().strip(string.punctuation)
        if clean_curr == clean_prev:
            continue
        result.append(word)
    return " ".join(result)


# ─────────────────────────────────────────────────────────────────────────────
# CLI quick-test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_keywords = [
        "engineering",
        "engineering Noida",
        "data engineer",
        "python",
        "AI",
        "software companies Noida",
    ]

    for kw in test_keywords:
        tasks = generate_search_tasks(kw)
        from query.intent_classifier import classify_intent
        intent = classify_intent(kw)
        print(f"\n{'='*60}")
        print(f"Keyword : {kw!r}  →  intent={intent}  tasks={len(tasks)}")
        print(f"{'='*60}")
        for t in tasks[:15]:
            print(f"  [{t.source}]  {t.query}")
        if len(tasks) > 15:
            print(f"  ... and {len(tasks) - 15} more")