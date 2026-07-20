"""
semantic/semantic_intent_resolver.py
====================================
Resolves user search keywords into an IntentProfile using the B2B ontology.
"""

from semantic.semantic_profile import IntentProfile
from semantic.ontology_manager import OntologyManager, ConceptNormalizer

class SemanticIntentResolver:
    def __init__(self, ontology_manager: OntologyManager = None):
        self.om = ontology_manager or OntologyManager()

    def resolve(self, keyword: str) -> IntentProfile:
        """Resolve a raw keyword into a structured IntentProfile, merging multi-intents."""
        kw_clean = keyword.lower().strip()
        
        # Remove true noise words: location names, superlatives, and generic containers
        # that add nothing to domain resolution. Keep all industry-specific words.
        generic_noises = {
            "noida", "delhi", "mumbai", "bangalore", "hyderabad", "chennai",
            "pune", "kolkata", "gurgaon", "india", "best", "top", "leading",
            "pvt", "ltd", "inc", "llc",
        }
        words = [w for w in kw_clean.split() if w not in generic_noises and len(w) > 2]
        
        matched_domains = []
        concepts = set()
        positions = set()
        services = set()
        products = set()
        
        # 1. Try to find domain for full keyword
        domain = self.om.find_closest_domain(kw_clean, self.om.ontology)
        if domain:
            matched_domains.append(domain)
            
        # 2. Try to resolve sub-words separately
        for w in words:
            w_domain = self.om.find_closest_domain(w, self.om.ontology)
            if w_domain and w_domain not in matched_domains:
                matched_domains.append(w_domain)

        # 3. Merge multiple matched domains
        if matched_domains:
            primary = matched_domains[0].title()
            if len(matched_domains) > 1:
                primary = " + ".join(d.title() for d in matched_domains)
                
            for d in matched_domains:
                ch = self.om.ontology[d]
                concepts.update(ch.get("concepts", []))
                positions.update(ch.get("positions", []))
                services.update(ch.get("services", []))
                products.update(ch.get("products", []))
                
            confidence = 1.0 if len(matched_domains) == 1 else 0.7
            
            return IntentProfile(
                primary_domain=primary,
                concepts=concepts,
                positions=positions,
                services=services,
                products=products,
                confidence=confidence,
                ontology_version=self.om.version
            )
            
        # 4. Fallback Dynamic Generator for unknown keywords
        norm_kw = ConceptNormalizer.normalize(kw_clean)
        concepts = {norm_kw}
        for w in words:
            concepts.add(ConceptNormalizer.normalize(w))
            
        # Generate B2B/Roles variations AND include common adjacent terms
        # that real companies use on their pages
        positions = {
            ConceptNormalizer.normalize(norm_kw + " Developer"),
            ConceptNormalizer.normalize(norm_kw + " Engineer"),
            ConceptNormalizer.normalize(norm_kw + " Specialist")
        }
        services = {
            ConceptNormalizer.normalize(norm_kw + " Development"),
            ConceptNormalizer.normalize(norm_kw + " Consulting"),
            ConceptNormalizer.normalize(norm_kw + " Solutions"),
            ConceptNormalizer.normalize(norm_kw + " Services"),
        }
        # Add the raw individual words as concepts too so snippet matching
        # can catch partial hits (e.g. "IT" alone, or "consulting" alone)
        for w in words:
            concepts.add(w)
            concepts.add(ConceptNormalizer.normalize(w))
        
        return IntentProfile(
            primary_domain=norm_kw,
            concepts=concepts,
            positions=positions,
            services=services,
            products=set(),
            confidence=0.4,
            ontology_version=self.om.version
        )
