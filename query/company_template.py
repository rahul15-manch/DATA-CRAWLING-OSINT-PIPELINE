"""
query/company_template.py
=========================
Search query templates for company discovery (Tasks 1 & 3).

Design rules
------------
1. Every Google template MUST contain a business-intent modifier.
   Generic bare-keyword searches pull in articles, tutorials, and Wikipedia.
2. Platform site: queries are kept bare — the site operator already filters
   to company profiles on that platform.
3. Templates are fully generic — {keyword} is the only variable.
   No industry names are hardcoded; the classification layer handles that.
4. Source diversity: 9 sources are queried, from Google to Crunchbase to
   Wellfound and Apollo, so each run covers web results + company directories
   + startup databases + professional networks.

Template count per source (approximate):
  google       14   (broad web crawl with business-intent variations)
  linkedin      2   (company profile pages only)
  clutch        2   (B2B service company profiles)
  goodfirms     2   (software + IT company profiles)
  crunchbase    2   (startup + funded company database)
  wellfound     2   (startup + tech company database)
  apollo        2   (B2B company contact database)
  zoominfo      2   (enterprise company database)
  justdial      2   (Indian local business directory)
  ----------
  Total        30+
"""

COMPANY_TEMPLATES = {

    # ── Broad web / Google ────────────────────────────────────────────────
    "google": [

        # Core company intent (Task 1 — first batch from user spec)
        "{keyword} company",
        "{keyword} companies",
        "{keyword} software",
        "{keyword} solutions",
        "{keyword} services",
        "{keyword} provider",
        "{keyword} consulting",
        "{keyword} consultancy",
        "{keyword} startup",
        "{keyword} firms",
        "{keyword} vendors",
        "{keyword} manufacturers",
        "{keyword} agency",

        # Expanded intent variants
        "industrial {keyword} company",
        "top {keyword} companies site:clutch.co OR site:goodfirms.co",

    ],

    # ── Professional network — company profiles only ───────────────────────
    "linkedin": [
        "site:linkedin.com/company {keyword}",
        "site:linkedin.com/company {keyword} company",
        "site:linkedin.com/in {keyword} founder",
        "site:linkedin.com/in {keyword} CEO",
        "site:linkedin.com/in {keyword} CTO",
        "site:linkedin.com/in {keyword} owner",
    ],

    # ── B2B software / agency directory ───────────────────────────────────
    "clutch": [
        "site:clutch.co {keyword}",
        "site:clutch.co {keyword} company",
    ],

    # ── Software + IT company registry ────────────────────────────────────
    "goodfirms": [
        "site:goodfirms.co {keyword}",
        "site:goodfirms.co {keyword} company",
    ],

    # ── Startup & funded company database ─────────────────────────────────
    "crunchbase": [
        "site:crunchbase.com/organization {keyword}",
        "site:crunchbase.com {keyword} startup",
    ],

    # ── Tech startup hiring platform ───────────────────────────────────────
    "wellfound": [
        "site:wellfound.com/company {keyword}",
        "site:wellfound.com {keyword} startup",
    ],

    # ── B2B sales & contact intelligence ──────────────────────────────────
    "apollo": [
        "site:apollo.io {keyword} company",
        "site:apollo.io {keyword} technologies",
    ],

    # ── Enterprise company database ────────────────────────────────────────
    "zoominfo": [
        "site:zoominfo.com/c {keyword}",
        "site:zoominfo.com {keyword} company",
    ],

    # ── Indian local & national business directory ─────────────────────────
    "justdial": [
        "site:justdial.com {keyword}",
        "site:justdial.com {keyword} company",
    ],
}
