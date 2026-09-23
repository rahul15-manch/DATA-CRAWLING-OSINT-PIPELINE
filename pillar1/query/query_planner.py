"""
query/query_planner.py
======================
Generates B2B dork queries optimized for specific search engines 
by leveraging resolved IntentProfile domains rather than generic templates.

Dual-lane discovery (entity queries)
--------------------------------------
When the user types a bare entity name (e.g. "swiggy"), the planner emits
two lanes of tasks:

  DIRECT lane   — identity-focused queries that point straight at the entity:
                    "swiggy", "swiggy official website",
                    "site:linkedin.com/company/swiggy", …
                  These are tagged discovery_mode="direct".

  EXPANDED lane — semantic expansion queries that find companies in the same
                  space: "swiggy company", "swiggy services", …
                  These are tagged discovery_mode="expanded" (default).

For topic/industry queries (e.g. "AI companies", "software companies Noida")
only the EXPANDED lane runs, which is unchanged from previous behaviour.
"""

import re
import config
from semantic.semantic_intent_resolver import SemanticIntentResolver
from semantic.semantic_profile import IntentProfile
from models.search_task import SearchTask
from query.intent_classifier import is_entity_query

LOCATIONS = {"noida", "gurugram", "gurgaon", "chandigarh", "delhi", "ncr", "mumbai", "bangalore", "bengaluru", "pune", "hyderabad", "chennai", "kolkata", "jaipur", "ahmedabad"}

# ── Canonical expansions for common short-form category keywords ──────────────
# Used to generate high-signal direct queries without stuttering.
CATEGORY_ACRONYM_EXPANSIONS = {
    "ai":             ["artificial intelligence", "generative AI", "machine learning"],
    "ml":             ["machine learning", "deep learning"],
    "nlp":            ["natural language processing"],
    "cv":             ["computer vision"],
    "iot":            ["internet of things"],
    "rpa":            ["robotic process automation"],
    "saas":           ["SaaS", "software as a service"],
    "fintech":        ["financial technology", "fintech"],
    "cybersecurity":  ["cybersecurity", "information security", "infosec"],
    "cyber security": ["cybersecurity", "information security"],
    "blockchain":     ["blockchain", "distributed ledger"],
    "ar":             ["augmented reality"],
    "vr":             ["virtual reality"],
    "xr":             ["extended reality"],
    "edtech":         ["education technology", "e-learning"],
    "healthtech":     ["health technology", "digital health"],
    "medtech":        ["medical technology"],
    "cleantech":      ["clean technology", "cleantech"],
    "agritech":       ["agriculture technology"],
    "proptech":       ["property technology", "real estate technology"],
    "legaltech":      ["legal technology"],
    "hrtech":         ["HR technology", "human resources technology"],
    "martech":        ["marketing technology"],
    "adtech":         ["advertising technology"],
    "regtech":        ["regulatory technology"],
    "insurtech":      ["insurance technology"],
    "logistics":      ["logistics", "supply chain"],
    "ecommerce":      ["ecommerce", "e-commerce", "online retail"],
    "b2b":            ["B2B", "business-to-business"],
    "b2c":            ["B2C", "business-to-consumer"],
    "cloud":          ["cloud computing", "cloud services"],
    "devops":         ["DevOps", "continuous integration"],
    "defi":           ["decentralized finance", "DeFi"],
}


class QueryPlanner:
    def __init__(self, resolver: SemanticIntentResolver = None):
        self.resolver = resolver or SemanticIntentResolver()

    def plan_queries(self, keyword: str) -> list[SearchTask]:
        """Convert a user keyword into structured provider-specific SearchTasks based on its IntentProfile."""
        kw_clean = keyword.lower().strip()
        
        # Load search mode from config
        from config import SearchMode
        search_mode = getattr(config, "SEARCH_MODE", SearchMode.SEMANTIC)
        
        # 1. Extract location if present
        words = kw_clean.split()
        location = ""
        kw_no_loc = kw_clean
        if len(words) > 1 and words[-1] in LOCATIONS:
            location = words[-1].title()
            kw_no_loc = " ".join(words[:-1])
            
        loc_suffix = f" {location}" if location else ""
        tasks = []
        seen_queries = set()
        priority = 1

        def add_task(source: str, query: str, prepend: bool = False,
                     discovery_mode: str = "expanded"):
            nonlocal priority
            q_clean = " ".join(query.split()).strip()
            if not q_clean:
                return
            q_key = q_clean.lower()
            if q_key in seen_queries:
                return
            seen_queries.add(q_key)
            task = SearchTask(
                source=source,
                query=q_clean,
                priority=priority,
                category="company",
                discovery_mode=discovery_mode,
                original_keyword=keyword,
            )
            if prepend:
                tasks.insert(0, task)
            else:
                tasks.append(task)
            priority += 1

        # ── DIRECT lane: entity-identity queries ───────────────────────────────
        # Only activated for bare entity/company name queries (e.g. "swiggy").
        # These queries are unambiguous and point straight at the entity,
        # bypassing the semantic matching pipeline (scored by entity_identity_bonus
        # in SemanticRanker).
        def generate_direct_entity_queries():
            """Emit high-signal identity-focused queries tagged discovery_mode='direct' in 3 strict tiers."""
            kw_slug = re.sub(r"[^a-z0-9]", "", kw_no_loc)
            
            # ── Tier 1: Core Identity Queries (Highest Priority) ──────────────
            add_task("google", f"{kw_no_loc}", discovery_mode="direct")
            add_task("google", f"\"{kw_no_loc}\"", discovery_mode="direct")
            add_task("google", f"site:{kw_slug}.com", discovery_mode="direct")
            add_task("linkedin", f"site:linkedin.com/company/{kw_slug}", discovery_mode="direct")

            # ── Tier 2: Official Site & LinkedIn Variants ─────────────────────
            add_task("google", f"{kw_no_loc} official website", discovery_mode="direct")
            add_task("brave", f"{kw_no_loc} official site", discovery_mode="direct")
            add_task("google", f"{kw_no_loc} linkedin company", discovery_mode="direct")
            add_task("google", f"intitle:\"{kw_no_loc}\"", discovery_mode="direct")
            add_task("bing", f"{kw_no_loc} company headquarters{loc_suffix}", discovery_mode="direct")

            # ── Tier 3: Industry Directories ─────────────────────────────────
            add_task("clutch", f"site:clutch.co {kw_no_loc}", discovery_mode="direct")
            add_task("goodfirms", f"site:goodfirms.co {kw_no_loc}", discovery_mode="direct")

        # Helper to generate literal exact queries (EXPANDED lane)
        def generate_exact_queries():
            add_task("google", f"{kw_no_loc}{loc_suffix}")
            add_task("google", f"{kw_no_loc} company{loc_suffix}")
            add_task("google", f"{kw_no_loc} services{loc_suffix}")
            add_task("google", f"{kw_no_loc} solutions{loc_suffix}")
            add_task("google", f"{kw_no_loc} consulting{loc_suffix}")
            add_task("brave", f"{kw_no_loc} company{loc_suffix}")
            add_task("duckduckgo", f"{kw_no_loc} services{loc_suffix}")
            add_task("bing", f"{kw_no_loc} solutions{loc_suffix}")
            add_task("google", f"intitle:{kw_no_loc}{loc_suffix}")
            add_task("linkedin", f"site:linkedin.com/company {kw_no_loc}{loc_suffix}")
            add_task("clutch", f"site:clutch.co {kw_no_loc}{loc_suffix}")
            add_task("goodfirms", f"site:goodfirms.co {kw_no_loc}{loc_suffix}")
            add_task("github", f"site:github.com {kw_no_loc} development{loc_suffix}")

        # ── Detect entity query and emit DIRECT lane first ─────────────────────
        entity_query = is_entity_query(kw_no_loc)
        if entity_query:
            print(f"[QueryPlanner] Entity query detected: '{kw_no_loc}' — enabling DIRECT+EXPANDED dual-lane")
            generate_direct_entity_queries()
        else:
            # ── CATEGORY direct lane ──────────────────────────────────────────
            # For broad category queries (e.g. "AI", "cybersecurity", "fintech"),
            # emit direct logical queries tagged discovery_mode="direct" so they
            # run before ANY semantic expansion and before LinkedIn tasks get
            # starved by 15+ general Google queries.
            print(f"[QueryPlanner] Category query detected: '{kw_no_loc}' — enabling DIRECT category lane")

            def generate_direct_category_queries():
                cat = kw_no_loc.strip()
                cat_lower = cat.lower()

                # Clean base category name by stripping redundant trailing company words to prevent stuttering
                cat_base = re.sub(r"\b(companies|company|firm|firms|startup|startups|agency|agencies|manufacturers|suppliers)\b", "", cat, flags=re.I).strip()
                cat_base = " ".join(cat_base.split()) or cat
                cat_base_lower = cat_base.lower()

                # Core direct web discovery queries (run high-intent open-web company discovery)
                add_task("google", f"{cat_base} companies{loc_suffix}", discovery_mode="direct")
                add_task("google", f"{cat_base} manufacturers{loc_suffix}", discovery_mode="direct")
                add_task("google", f"consumer {cat_base} companies{loc_suffix}", discovery_mode="direct")
                add_task("google", f"top {cat_base} companies{loc_suffix}", discovery_mode="direct")
                add_task("brave",  f"{cat_base} companies{loc_suffix}", discovery_mode="direct")

                # Acronym / canonical expansions (e.g. "AI" → "artificial intelligence companies")
                expansions = CATEGORY_ACRONYM_EXPANSIONS.get(cat_base_lower, [])
                for expansion in expansions[:2]:  # cap at 2 expansions to stay inside budget
                    add_task("google", f"{expansion} companies{loc_suffix}", discovery_mode="direct")
                    add_task("google", f"{expansion} manufacturers{loc_suffix}", discovery_mode="direct")

                # Clutch / GoodFirms direct category page
                add_task("clutch",    f"site:clutch.co {cat_base} companies{loc_suffix}", discovery_mode="direct")
                add_task("goodfirms", f"site:goodfirms.co {cat_base} companies{loc_suffix}", discovery_mode="direct")

            generate_direct_category_queries()

        if search_mode == SearchMode.EXACT:
            generate_exact_queries()
            return tasks

        # For hybrid mode, run exact queries first
        if search_mode == SearchMode.HYBRID:
            generate_exact_queries()

        # --- Semantic query planning (EXPANDED lane) ---

        intent = self.resolver.resolve(kw_no_loc)
        
        # Split composite domains if any (e.g. "Ai + Automation" -> [["ai", "automation"])
        domains = [d.strip().lower().replace(" ", "_") for d in intent.primary_domain.split("+")]
        
        # Fetch ranked concepts dynamically with relevance scoring threshold
        concepts = []
        MIN_RELEVANCE_THRESHOLD = 0.35
        
        for d in domains:
            domain_concepts = self.resolver.om.get_ranked_concepts(d, kw_no_loc, top_n=8)
            for c in domain_concepts:
                # Calculate concept relevance using word similarity
                words_kw = set(kw_no_loc.lower().split())
                words_c = set(c.lower().split())
                overlap = len(words_kw & words_c)
                rel_score = (overlap / float(len(words_kw))) if words_kw else 0.0
                
                # Broad match bonus if concept matches known domain
                if rel_score >= MIN_RELEVANCE_THRESHOLD or c.lower() in kw_no_loc.lower() or kw_no_loc.lower() in c.lower() or len(concepts) < 3:
                    if c not in concepts:
                        concepts.append(c)
            
        # Ensure user's keyword is always preserved at the top of concepts
        if kw_no_loc not in concepts:
            concepts.insert(0, kw_no_loc)

        concept_focus = concepts[0] if concepts else kw_no_loc

        from query.company_template import INDUSTRY_SEMANTIC_TEMPLATES

        # 1. Tech & Concept Family (Dynamic threshold expansion with industry-aware B2B templates)
        for concept in concepts:
            # Check if domain templates exist for any of the target domains
            applied_industry_templates = []
            for d in domains:
                if d in INDUSTRY_SEMANTIC_TEMPLATES:
                    applied_industry_templates.extend(INDUSTRY_SEMANTIC_TEMPLATES[d])

            if applied_industry_templates:
                for tmpl in applied_industry_templates[:5]:
                    raw_query = tmpl.format(concept=concept) + loc_suffix
                    # Sanitize: collapse consecutive duplicate words (case-insensitive)
                    # e.g. "ai AI company" → "AI company"
                    words_out = raw_query.split()
                    deduped = []
                    for w in words_out:
                        if not deduped or w.lower() != deduped[-1].lower():
                            deduped.append(w)
                    query_str = " ".join(deduped)
                    add_task("google", query_str)
                    add_task("brave", query_str)
            else:
                add_task("google", f"{concept} company{loc_suffix}")
                add_task("google", f"{concept} startups{loc_suffix}")
                add_task("google", f"{concept} software company{loc_suffix}")
                add_task("brave", f"{concept} company{loc_suffix}")
                add_task("duckduckgo", f"{concept} company{loc_suffix}")
                add_task("bing", f"{concept} company{loc_suffix}")

        # Domain-specific B2B intent expansions for hardware/electronics
        if "hardware_development" in domains:
            for p in ["google", "duckduckgo", "bing", "brave"]:
                add_task(p, f"electronics manufacturing company{loc_suffix}")
                add_task(p, f"PCB design company{loc_suffix}")
                add_task(p, f"embedded systems company{loc_suffix}")
                add_task(p, f"electronics design services{loc_suffix}")
                add_task(p, f"EMS company{loc_suffix}")
                add_task(p, f"electronic product development company{loc_suffix}")
                add_task(p, f"hardware design consultancy{loc_suffix}")

        # 2. Service Family (concept-based instead of generic hardcoded software)
        add_task("google", f"custom {concept_focus} development{loc_suffix}")
        add_task("brave", f"{concept_focus} outsourcing{loc_suffix}")
        add_task("duckduckgo", f"{concept_focus} consulting{loc_suffix}")

        # 3. Problem Family (concept-based instead of generic hardcoded software)
        add_task("google", f"{concept_focus} services{loc_suffix}")
        add_task("brave", f"enterprise {concept_focus} solutions{loc_suffix}")
        add_task("duckduckgo", f"custom {concept_focus} solutions{loc_suffix}")

        # 4. Directories & Social Profile pages
        for concept in concepts[:2]:
            add_task("linkedin", f"site:linkedin.com/company {concept}{loc_suffix}")
            add_task("clutch", f"site:clutch.co {concept}{loc_suffix}")
            add_task("goodfirms", f"site:goodfirms.co {concept}{loc_suffix}")
            add_task("github", f"site:github.com {concept} development{loc_suffix}")

        # 5. Raw Keyword fallback
        if location:
            add_task("google", f"{kw_no_loc}{loc_suffix}", prepend=True)
        add_task("google", keyword, prepend=True)

        return tasks

