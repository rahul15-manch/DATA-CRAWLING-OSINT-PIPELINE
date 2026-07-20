"""
semantic/semantic_matcher.py
============================
Pluggable Semantic Matcher architecture in Flowiz.
Computes weighted scores and explainability traces between IntentProfile and CompanyProfile.
"""

import os
import json
import re
from abc import ABC, abstractmethod
from semantic.semantic_profile import IntentProfile, CompanyProfile

DEFAULT_SEMANTIC_WEIGHTS = {
    "description": 30.0,
    "services": 25.0,
    "technologies": 20.0,
    "products": 10.0,
    "positions": 10.0,
    "blog": 5.0,
}

def load_semantic_weights() -> dict:
    path = "data/semantic_weights.json"
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SEMANTIC_WEIGHTS, f, indent=2, ensure_ascii=False)
        return DEFAULT_SEMANTIC_WEIGHTS
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_SEMANTIC_WEIGHTS

class BaseMatcher(ABC):
    @abstractmethod
    def match(self, intent: IntentProfile, company: CompanyProfile) -> dict:
        """Compute the semantic match score and trace payload."""
        pass

SPANISH_TRANSLATIONS = {
    "electronics": ["electrónica", "electrónico", "electrónicos"],
    "electronic": ["electrónica", "electrónico", "electrónicos"],
    "development": ["desarrollo", "desarrollador", "desarrolladores"],
    "developer": ["desarrollo", "desarrollador", "desarrolladores"],
    "engineering": ["ingeniería", "ingeniero", "ingenieros"],
    "engineer": ["ingeniería", "ingeniero", "ingenieros"],
    "design": ["diseño", "diseñador"],
    "services": ["servicios"],
    "company": ["compañía", "empresa", "empresas"],
    "software": ["software", "programa", "programación"],
    "hardware": ["hardware", "equipos"],
    "embedded systems": ["sistemas embebidos", "sistemas empotrados", "embebidos"],
    "automation": ["automatización", "control"],
    "robotics": ["robótica"],
    "custom software": ["software a medida", "desarrollo a medida"],
    "hardware development": ["desarrollo de hardware"],
    "software development": ["desarrollo de software", "desarrollo software"],
    "electronics manufacturing": ["fabricación electrónica", "fabricación de electrónica"],
    "electronics design": ["diseño electrónico", "diseño de electrónica"],
    "hardware design": ["diseño de hardware"]
}

class WeightedMatcher(BaseMatcher):
    def __init__(self):
        self.weights = load_semantic_weights()

    def _matches_any(self, text: str, concepts: set) -> bool:
        if not text or not concepts:
            return False
        text_lower = text.lower()
        for c in concepts:
            c_low = c.lower()
            pattern = r'\b' + re.escape(c_low) + r'\b'
            if re.search(pattern, text_lower):
                return True
            # Check Spanish translations
            translations = SPANISH_TRANSLATIONS.get(c_low, [])
            for t in translations:
                t_pattern = r'\b' + re.escape(t) + r'\b'
                if re.search(t_pattern, text_lower):
                    return True
            if c_low in {"electronics", "electronic"} and "electron" in text_lower:
                return True
        return False

    def _extract_matching(self, text: str, concepts: set) -> set:
        if not text or not concepts:
            return set()
        matched = set()
        text_lower = text.lower()
        for c in concepts:
            c_low = c.lower()
            pattern = r'\b' + re.escape(c_low) + r'\b'
            if re.search(pattern, text_lower):
                matched.add(c)
                continue
            
            # Check Spanish translations
            translations = SPANISH_TRANSLATIONS.get(c_low, [])
            found = False
            for t in translations:
                t_pattern = r'\b' + re.escape(t) + r'\b'
                if re.search(t_pattern, text_lower):
                    matched.add(c)
                    found = True
                    break
            if found:
                continue
                
            # Substring fallback for key root terms
            if c_low in {"electronics", "electronic"} and "electron" in text_lower:
                matched.add(c)
        return matched

    def match(self, intent: IntentProfile, company: CompanyProfile) -> dict:
        score_breakdown = {}
        matched_signals = []
        rejected_signals = []
        semantic_trace = []

        if company.is_snippet:
            # --- Snippet-level matching (scaled out of 60.0) ---
            # 1. Title (weight 20)
            title_text = company.sections.get("homepage", "")
            title_matches = self._extract_matching(title_text, intent.concepts)
            if title_matches:
                score_breakdown["title"] = 20.0
                matched_signals.append("Title")
                semantic_trace.append(f"Matched Title with concepts: {list(title_matches)}")
            else:
                score_breakdown["title"] = 0.0
                rejected_signals.append("Title")

            # 2. Description (weight 30)
            desc_text = company.description.get("value", "")
            desc_matches = self._extract_matching(desc_text, intent.concepts)
            if desc_matches:
                score_breakdown["description"] = 30.0
                matched_signals.append("Description")
                semantic_trace.append(f"Matched Description with concepts: {list(desc_matches)}")
            else:
                score_breakdown["description"] = 0.0
                rejected_signals.append("Description")

            # 3. Positions (weight 10)
            pos_matches = set()
            for cp in company.positions:
                cp_val = cp.get("value", "").lower()
                for ip in intent.positions:
                    if cp_val in ip.lower():
                        pos_matches.add(cp.get("value"))
                        break
            if pos_matches:
                score_breakdown["positions"] = 10.0
                matched_signals.append("Positions")
                semantic_trace.append(f"Matched Positions: {list(pos_matches)}")
            else:
                score_breakdown["positions"] = 0.0
                rejected_signals.append("Positions")

            total_weights = 60.0
            raw_score = sum(score_breakdown.values())
            normalized_score = (raw_score / total_weights) * 100.0
            final_confidence = (normalized_score / 100.0) * company.profile_confidence

            return {
                "score": int(normalized_score),
                "confidence": round(final_confidence, 2),
                "matched_signals": matched_signals,
                "rejected_signals": rejected_signals,
                "score_breakdown": score_breakdown,
                "company_type": company.company_type,
                "semantic_trace": semantic_trace
            }

        # --- Crawled HTML matching (scaled out of 100.0) ---
        # 1. Company Description matching concepts
        desc_text = company.description.get("value", "")
        desc_matches = self._extract_matching(desc_text, intent.concepts)
        if desc_matches:
            score_breakdown["description"] = self.weights["description"]
            matched_signals.append("Description")
            semantic_trace.append(f"Matched Description with concepts: {list(desc_matches)}")
        else:
            score_breakdown["description"] = 0.0
            rejected_signals.append("Description")

        # 2. Services matching services or concepts
        services_text = " ".join(s.get("value", "") for s in company.services) + " " + company.sections.get("services", "")
        serv_matches = self._extract_matching(services_text, intent.services | intent.concepts)
        if serv_matches:
            score_breakdown["services"] = self.weights["services"]
            matched_signals.append("Services")
            semantic_trace.append(f"Matched Services with terms: {list(serv_matches)}")
        else:
            score_breakdown["services"] = 0.0
            rejected_signals.append("Services")

        # 3. Technologies matching concepts
        tech_text = " ".join(t.get("value", "") for t in company.technologies)
        tech_matches = self._extract_matching(tech_text, intent.concepts)
        if tech_matches:
            score_breakdown["technologies"] = self.weights["technologies"]
            matched_signals.append("Technologies")
            semantic_trace.append(f"Matched Technologies: {list(tech_matches)}")
        else:
            score_breakdown["technologies"] = 0.0
            rejected_signals.append("Technologies")

        # 4. Products matching products
        prod_text = " ".join(p.get("value", "") for p in company.products) + " " + company.sections.get("products", "")
        prod_matches = self._extract_matching(prod_text, intent.products)
        if prod_matches:
            score_breakdown["products"] = self.weights["products"]
            matched_signals.append("Products")
            semantic_trace.append(f"Matched Products: {list(prod_matches)}")
        else:
            score_breakdown["products"] = 0.0
            rejected_signals.append("Products")

        # 5. Positions matching positions
        pos_text = " ".join(p.get("value", "") for p in company.positions)
        pos_matches = self._extract_matching(pos_text, intent.positions)
        if pos_matches:
            score_breakdown["positions"] = self.weights["positions"]
            matched_signals.append("Positions")
            semantic_trace.append(f"Matched Positions: {list(pos_matches)}")
        else:
            score_breakdown["positions"] = 0.0
            rejected_signals.append("Positions")

        # 6. Blog matching concepts
        blog_text = company.sections.get("blog", "") + " " + company.sections.get("careers", "")
        blog_matches = self._extract_matching(blog_text, intent.concepts)
        if blog_matches:
            score_breakdown["blog"] = self.weights["blog"]
            matched_signals.append("Blog/Articles")
            semantic_trace.append(f"Matched Blog/Articles with concepts: {list(blog_matches)}")
        else:
            score_breakdown["blog"] = 0.0
            rejected_signals.append("Blog/Articles")

        # Compute normalized score (Weights sum to 100.0)
        total_weights = sum(self.weights.values()) or 100.0
        raw_score = sum(score_breakdown.values())
        normalized_score = (raw_score / total_weights) * 100.0
        
        # Incorporate profile confidence into match confidence
        final_confidence = (normalized_score / 100.0) * company.profile_confidence
        
        return {
            "score": int(normalized_score),
            "confidence": round(final_confidence, 2),
            "matched_signals": matched_signals,
            "rejected_signals": rejected_signals,
            "score_breakdown": score_breakdown,
            "company_type": company.company_type,
            "semantic_trace": semantic_trace
        }
