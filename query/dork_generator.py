"""
query/dork_generator.py
=======================
Converts a raw user keyword into a list of SearchTask objects.

Pipeline
--------
1. Intent Classifier  →  detects intent, rewrites job-role / tech keywords
2. Template selection →  picks COMPANY_TEMPLATES (always; person discovery
                         is a separate Pillar 2 concern)
3. Task generation    →  one SearchTask per (source, template) pair

Design constraints
------------------
- NEVER generates person-oriented search templates (github, portfolio,
  email, phone, resume).  Those belong to contact discovery (Pillar 2).
- .gov, .gov.in, .gov.uk domains are never targeted.
- Forum domains (Reddit, Quora, Medium, StackOverflow, Zhihu) are never
  targeted.
"""

from query.company_template import COMPANY_TEMPLATES
from query.intent_classifier import classify_intent, expand_to_company_keywords
from models.search_task import SearchTask


def generate_search_tasks(keyword: str) -> list[SearchTask]:
    """
    Generate a list of SearchTask objects for a given keyword.

    Parameters
    ----------
    keyword : str
        Raw user input, e.g. "data engineer", "python", "AI startup"

    Returns
    -------
    list[SearchTask]
        Ordered list of search tasks, highest-priority first.
        Category is always "company" — person discovery is Pillar 2.
    """
    keyword = keyword.strip()
    if not keyword:
        return []

    # ── Step 1: Intent classification + keyword rewrite ───────────────────
    intent       = classify_intent(keyword)
    company_kws  = expand_to_company_keywords(keyword)

    tasks    = []
    priority = 1
    seen_queries: set[str] = set()

    # ── Step 2: Generate tasks for each expanded keyword ──────────────────
    for company_kw in company_kws:
        for source, templates in COMPANY_TEMPLATES.items():
            for template in templates:
                query = template.format(keyword=company_kw)

                # Deduplicate repeated words introduced when an expansion
                # already contains business-intent words (e.g.
                # "data engineering company" + template " {keyword} company"
                # → "data engineering company company").
                query = _collapse_repeated_words(query)

                # Skip exact duplicate queries across all keywords/templates
                q_key = query.lower().strip()
                if q_key in seen_queries:
                    continue
                seen_queries.add(q_key)

                task  = SearchTask(
                    source=source,
                    query=query,
                    priority=priority,
                    category="company",   # always "company" — never "person"
                )
                tasks.append(task)
                priority += 1

    return tasks


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
    words  = query.split()
    result = [words[0]] if words else []
    for word in words[1:]:
        if word.lower() != result[-1].lower():
            result.append(word)
    return " ".join(result)


# ─────────────────────────────────────────────────────────────────────────────
# CLI quick-test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_keywords = [
        "data engineer",
        "python",
        "AI",
        "software companies",
        "automation",
        "digital marketing",
    ]

    for kw in test_keywords:
        tasks = generate_search_tasks(kw)
        intent = classify_intent(kw)
        print(f"\n{'='*60}")
        print(f"Keyword : {kw!r}  →  intent={intent}  tasks={len(tasks)}")
        print(f"{'='*60}")
        for t in tasks[:5]:
            print(f"  [{t.source}]  {t.query}")
        if len(tasks) > 5:
            print(f"  ... and {len(tasks) - 5} more")