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

    # ── Step 1: Semantic intent expansion ───────────────────────────────────
    company_kws = build_semantic_company_variants(keyword)

    # Heuristic location extraction
    LOCATIONS = {"noida", "gurugram", "gurgaon", "chandigarh", "delhi", "ncr", "mumbai", "bangalore", "bengaluru", "pune", "hyderabad", "chennai", "kolkata", "jaipur", "ahmedabad"}

    ranked_candidates: list[tuple[int, float, int, str, str]] = []
    order = 0
    seen_queries: set[str] = set()

    def _add_candidate(source: str, query: str, priority_bonus: int) -> None:
        nonlocal order
        q_key = query.lower().strip()
        if q_key in seen_queries:
            return
        seen_queries.add(q_key)
        # Use priority_bonus as the primary sort key instead of just candidate rank
        rank = rank_query_candidate(query)
        ranked_candidates.append((priority_bonus, rank, order, source, query))
        order += 1

    # ── Step 2: Generate tasks applying source operators after semantics ──────
    for kw in company_kws:
        words = kw.strip().split()
        location = ""
        if len(words) > 1 and words[-1].lower() in LOCATIONS:
            location = words[-1]
            kw_no_loc = " ".join(words[:-1])
        else:
            kw_no_loc = kw

        for src_dict in COMPANY_TEMPLATES:
            source = src_dict["source"]
            templates = src_dict["templates"]
            source_priority = src_dict.get("priority", 50)
            
            for template in templates:
                query = template.format(keyword=kw_no_loc, location=location).strip()
                # Clean up multiple spaces if location was empty
                query = " ".join(query.split())

                if source in {"linkedin", "clutch", "goodfirms", "crunchbase", "wellfound", "apollo", "zoominfo", "justdial"}:
                    query = f"{query} -site:wikipedia.org -site:play.google.com -site:apps.apple.com -site:chromewebstore.google.com -site:whatsapp.com"

                # Incorporate source_priority into the candidate score
                _add_candidate(source, _collapse_repeated_words(query), source_priority)

    # Sort by priority_bonus (desc), rank (desc), order (asc)
    for idx, (_, _, _, source, query) in enumerate(sorted(ranked_candidates, key=lambda item: (-item[0], -item[1], item[2])), start=1):
        yield SearchTask(
            source=source,
            query=query,
            priority=idx,
            category="company",
        )


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