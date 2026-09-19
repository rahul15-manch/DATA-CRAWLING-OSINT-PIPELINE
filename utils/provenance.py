"""
Provenance source labels for observed facts.
Used by page_extractor.py and build_lead_card in main.py.

RULE: observed=True means the value was seen in an actual source.
      verified=False means we have not independently confirmed it.
      verified=True is reserved for future active verification steps.
"""

# Where a value was observed
SRC_HOMEPAGE_MAILTO           = "homepage_mailto"           # <a href="mailto:...">
SRC_HOMEPAGE_TEXT             = "homepage_text"             # regex on homepage body
SRC_HOMEPAGE_STRUCTURED       = "homepage_structured_data"  # JSON-LD / schema.org on homepage
SRC_CONTACT_PAGE_TEXT         = "contact_page_text"         # regex on /contact subpage
SRC_CONTACT_PAGE_STRUCTURED   = "contact_page_structured_data"
SRC_ABOUT_PAGE_TEXT           = "about_page_text"           # regex on /about subpage
SRC_ABOUT_PAGE_STRUCTURED     = "about_page_structured_data"
SRC_TEAM_PAGE_TEXT            = "team_page_text"
SRC_SEARCH_RESULT_SNIPPET     = "search_result_snippet"     # found in search engine snippet
SRC_JSON_LD_HOMEPAGE          = "json_ld_homepage"          # JSON-LD numberOfEmployees / address on homepage
SRC_JSON_LD_SUBPAGE           = "json_ld_subpage"           # JSON-LD on any subpage
SRC_META_GEO_TAG              = "meta_geo_tag"              # <meta name="geo.country">
SRC_GENERATED_PATTERN         = "generated_pattern"         # pattern-generated, not observed


def make_fact(value, source: str, source_url: str = "", observed: bool = True, verified: bool = False) -> dict:
    """Build a single provenance fact dict."""
    return {
        "value":      value,
        "source":     source,
        "source_url": source_url or "",
        "observed":   observed,
        "verified":   verified,
    }