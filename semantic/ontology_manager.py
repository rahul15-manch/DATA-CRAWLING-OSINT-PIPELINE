"""
semantic/ontology_manager.py
============================
Manages hierarchical B2B ontologies, versioning, concept normalization,
and threshold-based term promotions.
"""

import os
import json
import re

ONTOLOGY_VERSION = "1.0.0"

# ---------- Concept Normalizer ----------

class ConceptNormalizer:
    _NORM_MAP = {
        "fast api": "FastAPI",
        "fastapi": "FastAPI",
        "fast-api": "FastAPI",
        "artificial intelligence": "AI",
        "artificial-intelligence": "AI",
        "machine learning": "ML",
        "machine-learning": "ML",
        "natural language processing": "NLP",
        "large language model": "LLM",
        "large language models": "LLM",
        "robotic process automation": "RPA",
        "industrial internet of things": "IIoT",
        "industrial iot": "IIoT",
        "iiot": "IIoT",
        "internet of things": "IoT",
        "iot": "IoT",
        "vector database": "Vector DB",
        "vector db": "Vector DB",
        "computer vision": "Computer Vision",
        "deep learning": "Deep Learning",
        "generative ai": "Generative AI",
        "open source": "Open Source",
        "k8s": "Kubernetes",
        "iac": "IaC",
        "oem": "OEM",
        "crm": "CRM",
    }

    @classmethod
    def normalize(cls, term: str) -> str:
        if not term:
            return ""
        lowered = term.lower().strip()
        # Remove version numbers or trailing noise
        lowered = re.sub(r"\s*v\d+(\.\d+)*$", "", lowered)
        
        # Check map
        if lowered in cls._NORM_MAP:
            return cls._NORM_MAP[lowered]
            
        # Default to title case
        return term.strip().title()

# ---------- Default Bootstrap Ontology ----------

BOOTSTRAP_ONTOLOGY = {
    "automation": {
        "concepts": ["automation", "plc", "scada", "mes", "dcs", "iiot", "mechatronics", "robotics", "rpa", "control systems", "factory automation", "industrial automation"],
        "positions": ["automation engineer", "plc programmer", "robotics engineer", "rpa developer", "control engineer"],
        "services": ["factory automation setup", "plc programming services", "industrial control solutions", "robotic process automation implementation"],
        "products": ["siemens", "abb", "rockwell", "fanuc", "kuka", "uipath", "blue prism"]
    },
    "ai": {
        "concepts": ["ai", "ml", "nlp", "llm", "deep learning", "computer vision", "generative ai", "neural network", "natural language processing", "vector db", "transformers", "gpt", "rag"],
        "positions": ["ai engineer", "machine learning engineer", "ml engineer", "data scientist", "nlp engineer", "computer vision specialist"],
        "services": ["ai consulting", "machine learning solutions", "llm fine-tuning", "generative ai development"],
        "products": ["langchain", "crewai", "dspy", "ollama", "openai", "claude", "gemini", "chatgpt"]
    },
    "fintech": {
        "concepts": ["blockchain", "billing", "accounting", "invoicing", "finance", "banking", "cryptocurrency", "ledger", "fintech", "payment gateway"],
        "positions": ["fintech developer", "blockchain engineer", "financial analyst"],
        "services": ["payment processing", "accounting software development", "blockchain consulting"],
        "products": ["stripe", "paypal", "ethereum", "solidity"]
    },
    "healthcare": {
        "concepts": ["medical software", "digital health", "telemedicine", "ehr", "clinical trials", "healthtech", "clinic"],
        "positions": ["healthcare consultant", "ehr administrator", "clinical research coordinator"],
        "services": ["telemedicine app development", "clinical data management", "healthcare compliance auditing"],
        "products": ["epic systems", "cerner", "athenahealth"]
    },
    "ecommerce": {
        "concepts": ["ecommerce", "digital commerce", "retail tech", "shopping cart", "online store", "marketplace", "d2c", "b2c"],
        "positions": ["ecommerce strategist", "retail technologist", "shopify developer"],
        "services": ["shopify custom development", "payment gateway integration", "digital commerce operations"],
        "products": ["shopify", "magento", "woocommerce"]
    },
    "logistics": {
        "concepts": ["supply chain", "freight forwarding", "shipping", "tracking", "warehouse management", "fleet management", "delivery solutions", "logistics"],
        "positions": ["logistics coordinator", "supply chain analyst"],
        "services": ["warehouse automation", "fleet tracking setup", "logistics consulting"],
        "products": ["sap scm", "oracle otm"]
    },
    "cybersecurity": {
        "concepts": ["threat detection", "network security", "penetration testing", "firewall", "encryption", "identity access", "endpoint protection", "zero trust", "cybersecurity", "infosec"],
        "positions": ["security analyst", "penetration tester", "security architect", "ciso"],
        "services": ["vulnerability scanning", "penetration testing services", "cybersecurity audits"],
        "products": ["okta", "crowdstrike", "splunk"]
    },
    "software_development": {
        "concepts": [
            "python", "django", "fastapi", "flask", "node.js", "react", "vue",
            "backend", "frontend", "full stack", "rest api", "graphql",
            "microservices", "web development", "custom software", "software development",
            "software engineering", "saas", "enterprise software", "software consulting",
            "it services", "software outsourcing", "it consulting", "api development"
        ],
        "positions": [
            "python developer", "backend engineer", "full stack developer",
            "software engineer", "web developer", "api developer"
        ],
        "services": [
            "custom software development", "web application development",
            "python development services", "api development", "backend development",
            "software outsourcing", "it consulting"
        ],
        "products": [
            "python", "django", "fastapi", "flask", "postgresql", "redis",
            "docker", "kubernetes", "aws", "azure", "gcp"
        ]
    },
    "hardware_industrial": {
        "concepts": ["hardware store", "industrial hardware", "tools", "equipment", "retailer", "supplies", "building materials", "diy", "screws", "fasteners", "power tools", "valves", "pumps", "machinery"],
        "positions": ["store manager", "hardware specialist", "sales associate", "inventory coordinator"],
        "services": ["hardware retail", "tool rental", "equipment supply", "industrial supply"],
        "products": ["ace hardware", "home depot", "lowes", "grainger", "mcmaster-carr"]
    },
    "hardware_development": {
        "concepts": [
            "hardware", "hardware development", "embedded systems", "iot", "pcb design", "firmware",
            "microcontrollers", "semiconductors", "electronics", "circuit design", "hardware engineering",
            "electronics manufacturing", "electronics design", "ems", "electronic product development",
            "hardware design", "oem manufacturing", "industrial automation", "semiconductor startups",
            "embedded software", "pcb assembly", "embedded systems companies", "electronics manufacturers"
        ],
        "positions": ["hardware engineer", "embedded developer", "electronics engineer", "firmware engineer"],
        "services": ["hardware design", "embedded systems development", "pcb design services", "iot product design"],
        "products": ["microcontrollers", "pcb", "sensors", "arduino", "raspberry pi"]
    },
    "devops_cloud": {
        "concepts": ["devops", "cloud computing", "ci/cd", "serverless", "kubernetes", "containerization", "sre", "cloud infrastructure", "terraform", "iac"],
        "positions": ["devops engineer", "cloud architect", "site reliability engineer", "sre", "cloud engineer"],
        "services": ["cloud migration", "devops consulting", "kubernetes orchestration", "infrastructure automation"],
        "products": ["kubernetes", "docker", "terraform", "aws", "azure", "gcp", "ansible"]
    },
    "b2b_saas_sales": {
        "concepts": ["saas", "b2b saas", "crm", "marketing automation", "sales enablement", "customer success", "lead generation", "plg"],
        "positions": ["saas founder", "account executive", "customer success manager", "sdr", "sales director"],
        "services": ["saas development", "crm implementation", "sales automation", "b2b lead generation"],
        "products": ["salesforce", "hubspot", "outreach", "gong", "apollo"]
    },
    "startup_services": {
        "concepts": ["incubator", "accelerator", "startup directory", "founder community", "funding platform", "venture capital", "investor network", "pitch deck", "equity management"],
        "positions": ["community manager", "investment associate", "program manager", "accelerator director"],
        "services": ["startup acceleration", "founder matching", "fundraising assistance", "investor relations"],
        "products": ["f6s", "angel-list", "crunchbase", "dealroom", "gust", "carta"]
    }
}

# ---------- Ontology Manager ----------

class OntologyManager:
    def __init__(self):
        self.static_path = "data/industry_semantics.json"
        self.learned_path = "data/learned_semantics.json"
        self.version = ONTOLOGY_VERSION
        self.ontology = self._load_and_merge()

    def _load_and_merge(self) -> dict:
        os.makedirs("data", exist_ok=True)
        
        # 1. Load static bootstrap ontology (always overwrite/sync to apply updates)
        try:
            with open(self.static_path, "w", encoding="utf-8") as f:
                json.dump(BOOTSTRAP_ONTOLOGY, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to write bootstrap ontology to {self.static_path}: {e}")
        static = BOOTSTRAP_ONTOLOGY

        # Detect and migrate old flat-list formats
        is_old = False
        if isinstance(static, dict):
            for k, v in static.items():
                if isinstance(v, list):
                    is_old = True
                    break
        else:
            is_old = True

        if is_old:
            static = BOOTSTRAP_ONTOLOGY
            with open(self.static_path, "w", encoding="utf-8") as f:
                json.dump(BOOTSTRAP_ONTOLOGY, f, indent=2, ensure_ascii=False)

        # Normalize static ontology terms
        normalized_static = {}
        for domain, channels in static.items():
            normalized_static[domain] = {
                "concepts": [ConceptNormalizer.normalize(t) for t in channels.get("concepts", [])],
                "positions": [ConceptNormalizer.normalize(t) for t in channels.get("positions", [])],
                "services": [ConceptNormalizer.normalize(t) for t in channels.get("services", [])],
                "products": [ConceptNormalizer.normalize(t) for t in channels.get("products", [])]
            }

        # 2. Load learned dynamic ontology
        if not os.path.exists(self.learned_path):
            with open(self.learned_path, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2, ensure_ascii=False)
            learned = {}
        else:
            try:
                with open(self.learned_path, "r", encoding="utf-8") as f:
                    learned = json.load(f)
            except Exception:
                learned = {}

        # 3. Merge learned terms based on promotion threshold (confidence > 0.75 AND accepted >= 3)
        promotions_count = 0
        rejections_count = 0
        
        for kw, candidates in learned.items():
            # Find closest matching domain
            domain = self.find_closest_domain(kw, normalized_static)
            if not domain:
                continue
                
            for term, stats in candidates.items():
                seen = stats.get("seen", 0)
                accepted = stats.get("accepted", 0)
                confidence = stats.get("confidence", 0.0)
                target_field = stats.get("target_field", "concepts")
                
                # Verify confidence logic
                if seen > 0:
                    confidence = accepted / seen
                    stats["confidence"] = confidence

                if confidence >= 0.75 and accepted >= 3:
                    norm_term = ConceptNormalizer.normalize(term)
                    # Add to static domain runtime
                    if norm_term not in normalized_static[domain].get(target_field, []):
                        normalized_static[domain][target_field].append(norm_term)
                        promotions_count += 1
                else:
                    rejections_count += 1

        # Track pipeline metrics internally if stats_tracker is imported elsewhere
        # We store these stats in stats tracker when matching is run
        self._promotions = promotions_count
        self._rejections = rejections_count

        return normalized_static

    def find_closest_domain(self, keyword: str, ontology: dict) -> str:
        """Find the matching ontology domain for the given keyword."""
        kw_clean = keyword.lower().strip()
        norm_kw = ConceptNormalizer.normalize(kw_clean)
        
        # 1. Exact match on domain key
        if kw_clean in ontology:
            return kw_clean
            
        # 2. Check exact matches in terms first (Priority 2)
        for domain, channels in ontology.items():
            for ch_name, terms in channels.items():
                if norm_kw in terms or any(kw_clean == t.lower() for t in terms):
                    return domain
                    
        # 3. Check substring/partial matches (Priority 3)
        matches = []
        for domain, channels in ontology.items():
            if kw_clean in domain:
                matches.append((domain, len(domain)))
            for ch_name, terms in channels.items():
                for t in terms:
                    if kw_clean in t.lower():
                        matches.append((domain, len(t)))
                        
        if matches:
            # Return the match with the shortest term length (most specific)
            matches.sort(key=lambda x: x[1])
            return matches[0][0]
            
        return ""

    def get_ranked_concepts(self, domain: str, keyword: str, top_n: int = 5) -> list[str]:
        """Rank concepts based on keyword string similarity + historical template feedback."""
        concepts = self.ontology.get(domain, {}).get("concepts", [])
        if not concepts:
            return []

        from query.expansion import get_query_feedback_snapshot
        feedback = get_query_feedback_snapshot()

        scored = []
        for c in concepts:
            # 1. Similarity score (Jaccard overlap)
            kw_set = set(keyword.lower().split())
            c_set = set(c.lower().split())
            intersection = len(kw_set.intersection(c_set))
            union = len(kw_set.union(c_set))
            sim = intersection / max(1, union)

            # 2. Historical ROI score
            roi_points = 0.0
            queries_run = 0
            for q_key, stats in feedback.items():
                # check if concept or its variations are in key
                if c.lower() in q_key.lower():
                    roi_points += stats.get("score", 0)
                    queries_run += stats.get("queries_run", 0)
            
            hist_roi = roi_points / max(1, queries_run) if queries_run > 0 else 0.0

            # Weighted combination: 60% similarity, 40% historical ROI
            score = 0.6 * sim + 0.4 * (hist_roi / 10.0)
            scored.append((c, score))

        scored.sort(key=lambda x: -x[1])
        return [item[0] for item in scored[:top_n]]
