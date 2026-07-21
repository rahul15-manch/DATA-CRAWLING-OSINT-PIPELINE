"""
query/query_planner.py
======================
Generates B2B dork queries optimized for specific search engines 
by leveraging resolved IntentProfile domains rather than generic templates.
"""

import re
import config
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

        def add_task(source: str, query: str, prepend: bool = False):
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
                category="company"
            )
            if prepend:
                tasks.insert(0, task)
            else:
                tasks.append(task)
            priority += 1

        # Helper to generate literal exact queries
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

        if search_mode == SearchMode.EXACT:
            generate_exact_queries()
            return tasks

        # For hybrid mode, run exact queries first
        if search_mode == SearchMode.HYBRID:
            generate_exact_queries()

        # --- Semantic query planning ---
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

        concept_focus = concepts[0] if concepts else kw_no_loc

        # 1. Tech & Concept Family
        for concept in concepts[:3]:
            add_task("google", f"{concept} company{loc_suffix}")
            add_task("google", f"{concept} software company{loc_suffix}")
            add_task("google", f"{concept} development company{loc_suffix}")
            add_task("brave", f"{concept} company{loc_suffix}")
            add_task("duckduckgo", f"{concept} software company{loc_suffix}")
            add_task("bing", f"{concept} development company{loc_suffix}")

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
