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

def generate_search_tasks(keyword: str, deterministic: bool = False, max_budget: int = None):
    """
    Generate SearchTask objects for a given keyword using Intent Expansion.

    Parameters
    ----------
    keyword : str
        Raw user input, e.g. "data engineer", "python", "AI startup", "engineering"
    deterministic : bool
        If True, disables stochastic multi-armed bandit exploration for deterministic prioritization.
    max_budget : int, optional
        Maximum total queries to yield across all lanes.

    Yields
    ------
    SearchTask
        Ordered search tasks, highest-priority first.
        Category is always "company" — person discovery is Pillar 2.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return

    planner = QueryPlanner()
    tasks = list(planner.plan_queries(keyword))
    
    import random
    import os
    import config
    
    is_deterministic = deterministic or os.getenv("DETERMINISTIC_SEARCH_TASKS", "false").lower() in ("true", "1")
    
    direct_tasks = []   # DIRECT lane: entity identity queries — run first
    general_tasks = []  # EXPANDED lane, no advanced operators
    dork_tasks = []     # EXPANDED lane, with site:, inurl:, intitle:, filetype:
    
    for idx, t in enumerate(tasks):
        # DIRECT lane tasks bypass MAB weighting — identity-critical order
        if getattr(t, "discovery_mode", "expanded") == "direct":
            direct_tasks.append((10.0, idx, t))
            continue
            
        if not is_deterministic and random.random() < 0.15:
            weight = 1.0 + (1.0 / (idx + 1.0))
        else:
            weight = rank_query_candidate(t.query)
            
        # Group expanded tasks based on whether they contain advanced operators
        has_operator = any(op in t.query.lower() for op in ("site:", "inurl:", "intitle:", "filetype:"))
        if has_operator:
            dork_tasks.append((weight, idx, t))
        else:
            general_tasks.append((weight, idx, t))
            
    # Sort both expanded groups independently using Multi-Armed Bandit weights
    general_tasks.sort(key=lambda x: (-x[0], x[1]))
    dork_tasks.sort(key=lambda x: (-x[0], x[1]))
    
    direct_budget = getattr(config, "MAX_DIRECT_QUERIES_BUDGET", 10)
    expanded_budget = getattr(config, "MAX_QUERIES_BUDGET", 20)
    total_budget = max_budget if max_budget is not None else getattr(config, "MAX_TOTAL_SEARCH_BUDGET", 25)
    
    combined_expanded = general_tasks + dork_tasks
    yielded_seen = set()
    yielded_count = 0

    # Yield DIRECT tasks first (bounded by direct_budget & total_budget)
    for _, _, task in direct_tasks[:direct_budget]:
        q_norm = task.query.lower().strip()
        if q_norm in yielded_seen:
            continue
        yielded_seen.add(q_norm)
        yield task
        yielded_count += 1
        if yielded_count >= total_budget:
            return
        
    # Yield EXPANDED tasks up to expanded_budget & total_budget
    for _, _, task in combined_expanded[:expanded_budget]:
        q_norm = task.query.lower().strip()
        if q_norm in yielded_seen:
            continue
        yielded_seen.add(q_norm)
        yield task
        yielded_count += 1
        if yielded_count >= total_budget:
            return



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