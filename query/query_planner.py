"""
query/query_planner.py
======================
Generates B2B dork queries optimized for specific search engines 
by leveraging resolved IntentProfile domains rather than generic templates.
"""

import re
from semantic.semantic_intent_resolver import SemanticIntentResolver
from semantic.semantic_profile import IntentProfile
from models.search_task import SearchTask

LOCATIONS = {"noida", "gurugram", "gurgaon", "chandigarh", "delhi", "ncr", "mumbai", "bangalore", "bengaluru", "pune", "hyderabad", "chennai", "kolkata", "jaipur", "ahmedabad"}

class QueryPlanner:
    def __init__(self, resolver: SemanticIntentResolver = None):
        self.resolver = resolver or SemanticIntentResolver()

    def plan_queries(self, keyword: str) -> list[SearchTask]:
        """Convert a user keyword into structured provider-specific SearchTasks based on its IntentProfile."""
        kw_clean = keyword.lower().strip()
        
        # 1. Extract location if present
        words = kw_clean.split()
        location = ""
        kw_no_loc = kw_clean
        if len(words) > 1 and words[-1] in LOCATIONS:
            location = words[-1].title()
            kw_no_loc = " ".join(words[:-1])
            
        # 2. Resolve Intent Profile
        intent = self.resolver.resolve(kw_no_loc)
        
        # Split composite domains if any (e.g. "Ai + Automation" -> ["ai", "automation"])
        domains = [d.strip().lower().replace(" ", "_") for d in intent.primary_domain.split("+")]
        
        # Fetch ranked concepts dynamically
        concepts = []
        for d in domains:
            concepts.extend(self.resolver.om.get_ranked_concepts(d, kw_no_loc, top_n=3))
            
        # Ensure user's keyword is always preserved at the top of concepts
        if kw_no_loc not in concepts:
            concepts.insert(0, kw_no_loc)
            
        tasks = []
        seen_queries = set()
        priority = 1
        
        def add_task(source: str, query: str, prepend: bool = False):
            nonlocal priority
            q_clean = " ".join(query.split()).strip()
            if not q_clean:
                return
            q_key = q_clean.lower()
            if q_key in seen_queries:
                return
            seen_queries.add(q_key)
            # Note: no -site: exclusion operators — they cause VALID_ZERO_RESULTS on Google
            # and reduce recall without meaningful precision gain. Let Google's own ranking
            # filter Wikipedia / app-stores for B2B queries.
            task = SearchTask(
                source=source,
                query=q_clean,
                priority=priority,
                category="company"
            )
            if prepend:
                tasks.insert(0, task)
            else:
                tasks.append(task)
            priority += 1

        loc_suffix = f" {location}" if location else ""

        # --- Generate Diverse B2B Queries ---

        # 1. Tech & Concept Family (simple independent queries for the top concepts)
        for concept in concepts[:3]:
            add_task("google", f"{concept} company{loc_suffix}")
            add_task("google", f"{concept} software company{loc_suffix}")
            add_task("google", f"{concept} development company{loc_suffix}")
            add_task("brave", f"{concept} company{loc_suffix}")
            add_task("duckduckgo", f"{concept} software company{loc_suffix}")
            add_task("bing", f"{concept} development company{loc_suffix}")

        # 2. Service Family
        add_task("google", f"custom software development{loc_suffix}")
        add_task("brave", f"software outsourcing{loc_suffix}")
        add_task("duckduckgo", f"it consulting{loc_suffix}")

        # 3. Problem Family
        add_task("google", f"build rest api{loc_suffix}")
        add_task("brave", f"enterprise software{loc_suffix}")
        add_task("duckduckgo", f"crm development{loc_suffix}")

        # 4. Directories & Social Profile pages (Clutch, GoodFirms, GitHub, LinkedIn)
        for concept in concepts[:2]:
            add_task("linkedin", f"site:linkedin.com/company {concept}{loc_suffix}")
            add_task("clutch", f"site:clutch.co {concept}{loc_suffix}")
            add_task("goodfirms", f"site:goodfirms.co {concept}{loc_suffix}")
            add_task("github", f"site:github.com {concept} development{loc_suffix}")

        # 5. Raw Keyword fallback (Prepended so they run first)
        if location:
            add_task("google", f"{kw_no_loc}{loc_suffix}", prepend=True)
        add_task("google", keyword, prepend=True)

        return tasks
