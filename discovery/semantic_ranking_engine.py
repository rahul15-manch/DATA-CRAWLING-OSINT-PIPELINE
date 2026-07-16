"""
discovery/semantic_ranking_engine.py
====================================
Explainable Semantic Ranking Engine (SRE) for Pillar 1.
Implements dynamic concept expansion, normalized scoring, metadata-only parse optimization,
and online weight learning.
"""

import os
import json
import re
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup

# ---------- Constants & Default Configurations ----------

DEFAULT_WEIGHTS = {
    "title": 15.0,
    "meta_description": 20.0,
    "search_snippet": 15.0,
    "roles": 10.0,
    "about_page": 20.0,
    "services_page": 20.0,
    "homepage_body": 15.0,
    "schema_org": 10.0,
    "og": 5.0,
    "json_ld": 10.0,
}

BOOTSTRAP_SEMANTICS = {
    "automation": [
        "automation", "plc", "scada", "industrial control", "factory automation", 
        "robotics", "rpa", "uipath", "blue prism", "industrial automation",
        "siemens", "abb", "rockwell", "fanuc", "kuka", "iiot", "mechatronics"
    ],
    "ai": [
        "ai", "artificial intelligence", "machine learning", "ml", "nlp", "llm", 
        "deep learning", "computer vision", "generative ai", "neural network", 
        "natural language processing", "langchain", "rag", "ollama", "vector db", 
        "pytorch", "tensorflow", "transformers", "gpt"
    ],
    "fintech": [
        "payment gateway", "blockchain", "billing", "accounting", "invoicing", 
        "finance", "banking", "cryptocurrency", "smart contract", "credit", 
        "microfinance", "trading", "ledger", "fintech"
    ],
    "healthcare": [
        "medical software", "digital health", "telemedicine", "electronic health records", 
        "ehr", "clinical trials", "healthcare technology", "patient care", 
        "medical devices", "healthtech", "clinic"
    ],
    "ecommerce": [
        "ecommerce", "digital commerce", "retail tech", "payment gateway", 
        "shopping cart", "shopify", "online store", "marketplace", "d2c", 
        "b2c", "retailer"
    ],
    "logistics": [
        "supply chain", "freight forwarding", "shipping", "tracking", 
        "warehouse management", "fleet management", "delivery solutions", "logistics"
    ],
    "marketing": [
        "seo", "digital marketing", "content marketing", "lead generation", 
        "branding", "media buying", "social media marketing", "advertising", "adtech"
    ],
    "cybersecurity": [
        "threat detection", "network security", "penetration testing", "firewall", 
        "encryption", "identity access", "endpoint protection", "zero trust", 
        "cybersecurity", "infosec"
    ],
    "iot": [
        "internet of things", "connected devices", "smart hardware", "sensors", 
        "embedded systems", "firmware", "iot"
    ],
    "gaming": [
        "game studio", "esports", "unity", "unreal engine", "console gaming", 
        "mobile gaming", "game dev"
    ],
    "legal": [
        "legal software", "contract management", "case management", "document review", 
        "e-discovery", "legaltech", "law firm"
    ],
    "edtech": [
        "e-learning", "lms", "virtual classroom", "online courses", 
        "educational technology", "training platform", "edtech"
    ],
    "agriculture": [
        "smart farming", "crop monitoring", "agricultural technology", 
        "precision agriculture", "irrigation solutions", "agritech"
    ]
}

# In-memory batch feedback log
_batch_feedback = []

# ---------- Semantics & Weights IO Loader ----------

def load_industry_semantics() -> dict:
    path = "data/industry_semantics.json"
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(BOOTSTRAP_SEMANTICS, f, indent=2, ensure_ascii=False)
        return BOOTSTRAP_SEMANTICS
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return BOOTSTRAP_SEMANTICS

def load_relevance_weights() -> dict:
    path = "data/relevance_weights.json"
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_WEIGHTS, f, indent=2, ensure_ascii=False)
        return DEFAULT_WEIGHTS
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_WEIGHTS

def save_relevance_weights(weights: dict) -> None:
    path = "data/relevance_weights.json"
    os.makedirs("data", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(weights, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[SemanticRankingEngine] Error saving weights: {e}")

# ---------- Ranking Base Class ----------

class BaseRanker(ABC):
    @abstractmethod
    def score_snippet(self, title: str, snippet: str, keyword: str) -> dict:
        """Evaluate snippet-level relevance score."""
        pass

    @abstractmethod
    def score_html(self, html: str, keyword: str, snippet_res: dict) -> dict:
        """Evaluate HTML-level deep relevance score."""
        pass

# ---------- SemanticRanker Subclass Implementation ----------

class SemanticRanker(BaseRanker):
    def __init__(self):
        self.semantics = load_industry_semantics()
        self.weights = load_relevance_weights()

    def get_concepts(self, keyword: str) -> set[str]:
        """Dynamically extract semantic concepts based on the keyword."""
        keyword_clean = keyword.lower().strip()
        concepts = {keyword_clean}

        # Check in semantics values
        for domain, terms in self.semantics.items():
            if keyword_clean == domain or any(keyword_clean in t for t in terms):
                concepts.update(terms)

        # Word-split fallback
        for w in keyword_clean.split():
            if len(w) > 3:
                concepts.add(w)

        return concepts

    def _matches_concept(self, text: str, concepts: set[str]) -> bool:
        if not text:
            return False
        text_lower = text.lower()
        for concept in concepts:
            pattern = r'\b' + re.escape(concept) + r'\b'
            if re.search(pattern, text_lower):
                return True
        return False

    def detect_industry(self, text: str) -> str:
        if not text:
            return "Unknown"
        text_lower = text.lower()

        scores = {}
        for domain, terms in self.semantics.items():
            count = 0
            for term in terms:
                count += len(re.findall(r'\b' + re.escape(term) + r'\b', text_lower))
            if count > 0:
                scores[domain] = count

        if not scores:
            return "Unknown"

        return max(scores, key=scores.get).title()

    def score_snippet(self, title: str, snippet: str, keyword: str) -> dict:
        concepts = self.get_concepts(keyword)

        matched_signals = []
        rejected_signals = []
        score_breakdown = {}

        # 1. Title
        title_matched = self._matches_concept(title, concepts)
        matched_signals.append("Title") if title_matched else rejected_signals.append("Title")
        score_breakdown["title"] = self.weights["title"] if title_matched else 0.0

        # 2. Search snippet
        snippet_matched = self._matches_concept(snippet, concepts)
        matched_signals.append("Search snippet") if snippet_matched else rejected_signals.append("Search snippet")
        score_breakdown["search_snippet"] = self.weights["search_snippet"] if snippet_matched else 0.0

        # 3. Meta description (placeholder representation on snippet-level)
        meta_matched = self._matches_concept(snippet, concepts)
        matched_signals.append("Meta description") if meta_matched else rejected_signals.append("Meta description")
        score_breakdown["meta_description"] = self.weights["meta_description"] if meta_matched else 0.0

        # 4. Roles
        roles_list = ["engineer", "developer", "founder", "ceo", "director", "manager", "team", "president", "architect", "programmer"]
        roles_matched = any(self._matches_concept(title + " " + snippet, {r}) for r in roles_list)
        matched_signals.append("Employee roles") if roles_matched else rejected_signals.append("Employee roles")
        score_breakdown["roles"] = self.weights["roles"] if roles_matched else 0.0

        # Normalize snippet score (Sum of snippet weights = 60.0)
        snippet_sum = 60.0
        matched_sum = (
            score_breakdown["title"] +
            score_breakdown["meta_description"] +
            score_breakdown["search_snippet"] +
            score_breakdown["roles"]
        )
        score = int((matched_sum / snippet_sum) * 100)

        detected_industry = self.detect_industry(title + " " + snippet)

        return {
            "score": score,
            "tier": self.get_tier(score),
            "matched_signals": matched_signals,
            "rejected_signals": rejected_signals,
            "score_breakdown": score_breakdown,
            "industry": detected_industry,
            "confidence": score / 100.0,
            "aborted": False
        }

    def score_html(self, html: str, keyword: str, snippet_res: dict) -> dict:
        concepts = self.get_concepts(keyword)
        soup = BeautifulSoup(html, "html.parser")

        # Start with snippet breakdown
        matched_signals = list(snippet_res.get("matched_signals", []))
        rejected_signals = list(snippet_res.get("rejected_signals", []))
        score_breakdown = dict(snippet_res.get("score_breakdown", {}))

        # Parse meta description from HTML (overwrites snippet-level guess)
        meta_tag = soup.find("meta", attrs={"name": "description"})
        meta_content = meta_tag.get("content", "") if meta_tag else ""
        meta_matched = self._matches_concept(meta_content, concepts)
        if meta_matched:
            score_breakdown["meta_description"] = self.weights["meta_description"]
            if "Meta description" not in matched_signals:
                matched_signals.append("Meta description")
            if "Meta description" in rejected_signals:
                rejected_signals.remove("Meta description")

        # OpenGraph
        og_tag = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"property": "og:title"})
        og_content = og_tag.get("content", "") if og_tag else ""
        og_matched = self._matches_concept(og_content, concepts)
        matched_signals.append("OpenGraph") if og_matched else rejected_signals.append("OpenGraph")
        score_breakdown["og"] = self.weights["og"] if og_matched else 0.0

        # JSON-LD
        json_ld_matched = False
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                json_data = script.get_text()
                if self._matches_concept(json_data, concepts):
                    json_ld_matched = True
                    break
            except Exception:
                pass
        matched_signals.append("JSON-LD") if json_ld_matched else rejected_signals.append("JSON-LD")
        score_breakdown["json_ld"] = self.weights["json_ld"] if json_ld_matched else 0.0

        # Schema.org Organization microdata
        schema_matched = False
        orgs = soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/Organization")})
        for org in orgs:
            if self._matches_concept(org.get_text(), concepts):
                schema_matched = True
                break
        matched_signals.append("Schema.org Organization") if schema_matched else rejected_signals.append("Schema.org Organization")
        score_breakdown["schema_org"] = self.weights["schema_org"] if schema_matched else 0.0

        # Metadata-only stop optimization
        resolved_sum = (
            score_breakdown.get("title", 0.0) +
            score_breakdown.get("meta_description", 0.0) +
            score_breakdown.get("search_snippet", 0.0) +
            score_breakdown.get("roles", 0.0) +
            score_breakdown.get("og", 0.0) +
            score_breakdown.get("json_ld", 0.0) +
            score_breakdown.get("schema_org", 0.0)
        )
        # Max additional potential from body signals: About (20) + Services (20) + Body (15) = 55.
        if resolved_sum + 55.0 < 40.0:
            # Cannot reach LOW relevance threshold, abort parsing
            score = int((resolved_sum / 150.0) * 100)
            return {
                "score": score,
                "tier": "REJECT",
                "matched_signals": matched_signals,
                "rejected_signals": rejected_signals + ["About page", "Services page", "Homepage body"],
                "score_breakdown": score_breakdown,
                "industry": snippet_res.get("industry", "Unknown"),
                "confidence": score / 100.0,
                "aborted": True
            }

        body_text = soup.get_text()

        # Homepage body term density normalization
        body_words = body_text.split()
        total_words = len(body_words)
        body_matched = False
        if total_words > 0:
            match_count = 0
            body_text_lower = body_text.lower()
            for concept in concepts:
                match_count += len(re.findall(r'\b' + re.escape(concept) + r'\b', body_text_lower))
            density = match_count / total_words
            if density >= 0.005:  # 0.5% term density
                body_matched = True

        matched_signals.append("Homepage body") if body_matched else rejected_signals.append("Homepage body")
        score_breakdown["homepage_body"] = self.weights["homepage_body"] if body_matched else 0.0

        # About page link detection
        about_matched = False
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text().lower()
            if "about" in href or "about" in text or "who-we-are" in href:
                about_matched = True
                break
        matched_signals.append("About page") if about_matched else rejected_signals.append("About page")
        score_breakdown["about_page"] = self.weights["about_page"] if about_matched else 0.0

        # Services page link detection
        services_matched = False
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text().lower()
            if any(term in href or term in text for term in ("services", "products", "solutions", "what-we-do")):
                services_matched = True
                break
        matched_signals.append("Services page") if services_matched else rejected_signals.append("Services page")
        score_breakdown["services_page"] = self.weights["services_page"] if services_matched else 0.0

        # Full score calculation normalized to 150.0
        total_sum = sum(self.weights.values())  # 150.0
        final_score = sum(score_breakdown.values())
        score = int((final_score / total_sum) * 100)

        # Detect industry with full text
        detected_industry = self.detect_industry(body_text)

        return {
            "score": score,
            "tier": self.get_tier(score),
            "matched_signals": matched_signals,
            "rejected_signals": rejected_signals,
            "score_breakdown": score_breakdown,
            "industry": detected_industry,
            "confidence": score / 100.0,
            "aborted": False
        }

    def get_tier(self, score: int) -> str:
        if score >= 80:
            return "HIGH"
        elif score >= 60:
            return "MEDIUM"
        elif score >= 40:
            return "LOW"
        else:
            return "REJECT"

# ---------- Batch Online Weight Learning Helper Functions ----------

def record_feedback(action: str, matched_signals: list[str]) -> None:
    """Queue feedback events in-memory to update weights on end-of-run."""
    _batch_feedback.append((action, matched_signals))

def apply_batch_learning() -> None:
    """Save batch feedback logs to JSON file weights exactly once at end-of-run."""
    if not _batch_feedback:
        return

    weights = load_relevance_weights()
    for action, signals in _batch_feedback:
        for sig in signals:
            key = _signal_to_key(sig)
            if key in weights:
                if action == "reward":
                    weights[key] = min(50.0, weights[key] + 0.5)
                elif action == "penalize":
                    weights[key] = max(1.0, weights[key] - 0.5)

    save_relevance_weights(weights)
    _batch_feedback.clear()
    print("[SemanticRankingEngine] Online batch weight learning applied successfully.")

def _signal_to_key(signal_name: str) -> str:
    mapping = {
        "Title": "title",
        "Meta description": "meta_description",
        "Search snippet": "search_snippet",
        "Employee roles": "roles",
        "About page": "about_page",
        "Services page": "services_page",
        "Homepage body": "homepage_body",
        "Schema.org Organization": "schema_org",
        "OpenGraph": "og",
        "JSON-LD": "json_ld"
    }
    return mapping.get(signal_name, "")
