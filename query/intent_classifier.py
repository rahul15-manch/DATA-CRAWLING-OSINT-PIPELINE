"""
query/intent_classifier.py
==========================
Classifies raw user keywords into six intent categories and rewrites
job-role / technology keywords into company-discovery keywords.

Intent categories
-----------------
  company    — already a company/industry search  ("software companies")
  industry   — broad industry name               ("healthcare", "logistics")
  job_role   — person-oriented role word         ("data engineer", "python developer")
  technology — a tool/language/framework         ("python", "kubernetes", "react")
  product    — a concrete product name           ("crm", "erp", "saas platform")
  service    — a service offering                ("digital marketing", "seo services")

For job_role and technology intents the classifier rewrites the keyword
into company-discovery variants that are then fed to the dork generator
instead of the raw user keyword.

Design rules
------------
- No internet calls — purely rule-based.
- Falls through gracefully: unknown keywords are treated as "industry".
- Case-insensitive everywhere.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# Intent Keyword Sets
# ─────────────────────────────────────────────────────────────────────────────

# Words that signal the user is looking for a *person / role*
_JOB_ROLE_WORDS = frozenset({
    "engineer", "engineers",
    "developer", "developers",
    "designer", "designers",
    "manager", "managers",
    "director", "directors",
    "founder", "founders",
    "ceo", "cto", "coo", "cfo", "cmo",
    "president",
    "consultant", "consultants",
    "architect", "architects",
    "freelancer", "freelancers",
    "recruiter", "recruiters",
    "analyst", "analysts",
    "intern", "interns",
    "scientist", "scientists",
    "researcher", "researchers",
    "programmer", "programmers",
    "specialist", "specialists",
    "executive", "executives",
    "officer", "officers",
    "administrator", "administrators",
    "hr",
    "sales rep",
    "account manager",
    "project manager",
    "product manager",
    "marketing manager",
})

# Words that signal the user typed a pure technology / tool / language
_TECHNOLOGY_WORDS = frozenset({
    "python", "java", "javascript", "typescript", "golang", "go", "rust",
    "c++", "c#", "php", "ruby", "scala", "kotlin", "swift",
    "react", "angular", "vue", "django", "flask", "fastapi", "spring",
    "node", "nodejs", "next.js", "nuxt",
    "kubernetes", "docker", "terraform", "ansible",
    "aws", "azure", "gcp",
    "tensorflow", "pytorch", "scikit-learn", "opencv",
    "sql", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "blockchain", "ethereum", "solidity",
    "rpa", "uipath", "automation anywhere", "blue prism",
    "tableau", "powerbi", "power bi", "looker", "dbt",
    "hadoop", "spark", "kafka", "airflow",
    "android", "ios", "flutter", "react native",
    "ai", "ml", "nlp", "llm", "gpt",
    "selenium", "cypress", "playwright",
    "devops", "ci/cd", "jenkins",
})

# Words that signal the user typed a product category
_PRODUCT_WORDS = frozenset({
    "crm", "erp", "hrms", "hris", "cms", "lms",
    "saas", "paas", "iaas",
    "pos", "point of sale",
    "accounting software",
    "inventory management",
    "project management software",
    "chatbot",
    "helpdesk", "ticketing",
    "dashboard",
    "api gateway",
    "data warehouse",
    "analytics platform",
    "ecommerce platform",
    "payment gateway",
    "billing software",
})

# Words that signal the user typed a service type
_SERVICE_WORDS = frozenset({
    "digital marketing", "seo", "sem", "ppc",
    "content marketing", "email marketing",
    "social media marketing", "smm",
    "web design", "web development",
    "app development", "mobile development",
    "cloud migration", "cloud consulting",
    "cybersecurity services", "security audit",
    "data analytics", "business analytics",
    "staffing", "recruitment", "outsourcing",
    "managed services", "it support",
    "testing services", "qa services",
    "training services",
})

# Words that strongly confirm the user is searching for *companies*
_COMPANY_WORDS = frozenset({
    "company", "companies",
    "agency", "agencies",
    "startup", "startups",
    "firm", "firms",
    "business", "businesses",
    "consultancy",
    "corp", "corporation",
    "enterprise", "enterprises",
    "software",           # "software company" is already company-intent
    "technology", "technologies",
    "solutions", "solution",
    "services",           # "services company" → company
    "provider", "providers",
    "vendor", "vendors",
    "manufacturer", "manufacturers",
    "group",
    "inc", "ltd", "llc", "pvt",
    "industry", "industries",
})

# ─────────────────────────────────────────────────────────────────────────────
# Conversion Maps  (intent → company-search rewrites)
# ─────────────────────────────────────────────────────────────────────────────

# How to expand a job-role keyword into company-discovery keywords.
# Keys are matched as exact words inside the keyword string.
_JOB_ROLE_EXPANSION: dict[str, list[str]] = {
    "data engineer": [
        "data engineering company",
        "data engineering consultancy",
        "big data company",
        "ETL consulting company",
        "data pipeline company",
    ],
    "software engineer": [
        "software development company",
        "custom software company",
        "software engineering firm",
    ],
    "developer": [
        "software development company",
        "app development company",
        "web development agency",
    ],
    "designer": [
        "UI UX design agency",
        "product design company",
        "digital design studio",
    ],
    "machine learning engineer": [
        "machine learning company",
        "AI startup",
        "machine learning consultancy",
    ],
    "devops engineer": [
        "devops consulting company",
        "cloud infrastructure company",
        "devops services company",
    ],
    "security engineer": [
        "cybersecurity company",
        "information security firm",
        "security consulting company",
    ],
    "recruiter": [
        "staffing company",
        "recruitment agency",
        "talent acquisition firm",
    ],
    "hr": [
        "HR services company",
        "human resources consulting firm",
        "HR technology company",
    ],
    "analyst": [
        "data analytics company",
        "business analytics firm",
        "analytics consulting company",
    ],
}

# How to expand a technology keyword into company-discovery keywords.
_TECHNOLOGY_EXPANSION: dict[str, list[str]] = {
    "python": [
        "python development company",
        "python software company",
        "python consulting firm",
    ],
    "java": [
        "java development company",
        "java software company",
        "enterprise java company",
    ],
    "react": [
        "react development company",
        "react.js agency",
        "frontend development company",
    ],
    "node": [
        "node.js development company",
        "nodejs software company",
    ],
    "ai": [
        "AI startup",
        "artificial intelligence company",
        "AI solutions company",
        "AI consulting firm",
    ],
    "ml": [
        "machine learning company",
        "ML startup",
        "machine learning consultancy",
    ],
    "llm": [
        "large language model company",
        "generative AI company",
        "LLM startup",
    ],
    "blockchain": [
        "blockchain company",
        "blockchain startup",
        "web3 company",
    ],
    "devops": [
        "devops consulting company",
        "devops services company",
        "cloud devops firm",
    ],
    "kubernetes": [
        "kubernetes consulting company",
        "cloud infrastructure company",
        "container orchestration company",
    ],
    "aws": [
        "AWS cloud consulting company",
        "AWS managed services company",
    ],
    "azure": [
        "Microsoft Azure consulting company",
        "Azure cloud services company",
    ],
    "rpa": [
        "RPA company",
        "robotic process automation company",
        "RPA consulting firm",
    ],
    "uipath": [
        "UiPath implementation company",
        "UiPath consulting partner",
        "RPA automation company",
    ],
    "tableau": [
        "business intelligence company",
        "data visualization company",
        "analytics consulting firm",
    ],
    "selenium": [
        "QA automation company",
        "software testing company",
        "test automation firm",
    ],
}

# Generic fallback templates for job-role / technology intents
# when no exact match exists in the maps above.
# {keyword} is replaced with the original keyword stripped of role words.
_GENERIC_ROLE_TEMPLATES = [
    "{keyword} company",
    "{keyword} companies",
    "{keyword} consulting company",
    "{keyword} solutions company",
    "{keyword} services company",
]

_GENERIC_TECH_TEMPLATES = [
    "{keyword} development company",
    "{keyword} software company",
    "{keyword} consulting company",
    "{keyword} services company",
]


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def classify_intent(keyword: str) -> str:
    """
    Return one of:
        "company"   — keyword already targets companies
        "industry"  — broad industry / domain keyword
        "job_role"  — person / role keyword
        "technology"— tool / language / framework keyword
        "product"   — product category keyword
        "service"   — service offering keyword

    Parameters
    ----------
    keyword : str
        Raw user input, e.g. "data engineer", "python", "AI startup"
    """
    lower = keyword.lower().strip()
    words = set(lower.split())

    # ── Highest priority: explicit company search ──────────────────────────
    if words & _COMPANY_WORDS:
        return "company"

    # ── Job role detection ─────────────────────────────────────────────────
    if words & _JOB_ROLE_WORDS:
        return "job_role"

    # ── Technology detection ───────────────────────────────────────────────
    if lower in _TECHNOLOGY_WORDS or words & _TECHNOLOGY_WORDS:
        return "technology"

    # ── Product detection ──────────────────────────────────────────────────
    if lower in _PRODUCT_WORDS:
        return "product"

    # ── Service detection ──────────────────────────────────────────────────
    if lower in _SERVICE_WORDS:
        return "service"

    # ── Default: treat as industry ─────────────────────────────────────────
    return "industry"


def expand_to_company_keywords(keyword: str) -> list[str]:
    """
    Convert a raw keyword into a list of company-discovery search terms.

    For "company" and "industry" intents the original keyword is returned
    as-is (possibly with minor normalisation) — the dork generator appends
    its own business-intent modifiers.

    For "job_role" and "technology" intents the keyword is rewritten into
    concrete company-discovery phrases so that the dork generator never
    searches for persons.

    Parameters
    ----------
    keyword : str

    Returns
    -------
    list[str]
        One or more company-discovery keywords. Always non-empty.
    """
    intent = classify_intent(keyword)
    lower  = keyword.lower().strip()

    if intent == "job_role":
        # Try exact map first
        for role_key, expansions in _JOB_ROLE_EXPANSION.items():
            if role_key in lower:
                return expansions

        # Generic fallback — strip known role words and use the remainder
        core = _strip_role_words(lower)
        if core:
            return [t.format(keyword=core) for t in _GENERIC_ROLE_TEMPLATES]
        # Last resort
        return [f"{keyword} company", f"{keyword} firm"]

    if intent == "technology":
        # Try exact map first
        for tech_key, expansions in _TECHNOLOGY_EXPANSION.items():
            if tech_key == lower or tech_key in lower.split():
                return expansions

        # Generic fallback
        return [t.format(keyword=lower) for t in _GENERIC_TECH_TEMPLATES]

    if intent == "product":
        return [
            f"{keyword} company",
            f"{keyword} software company",
            f"{keyword} solutions provider",
            f"{keyword} vendor",
        ]

    if intent == "service":
        return [
            f"{keyword} company",
            f"{keyword} agency",
            f"{keyword} firm",
        ]

    # "company" or "industry" — return as-is; dork generator handles it
    return [keyword]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _strip_role_words(text: str) -> str:
    """
    Remove known job-role words from *text* and return the core domain word.

    Example:  "data engineer" → "data"
              "python developer" → "python"
    """
    tokens = text.split()
    return " ".join(t for t in tokens if t not in _JOB_ROLE_WORDS).strip()


# ─────────────────────────────────────────────────────────────────────────────
# CLI quick-test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        "data engineer",
        "python developer",
        "AI",
        "machine learning engineer",
        "software companies",
        "automation",
        "CRM",
        "digital marketing",
        "python",
        "devops",
        "recruiter",
        "healthcare",
    ]
    print(f"\n{'Keyword':<35} {'Intent':<15} Expansions")
    print("-" * 90)
    for kw in tests:
        intent     = classify_intent(kw)
        expansions = expand_to_company_keywords(kw)
        print(f"{kw:<35} {intent:<15} {expansions[:2]}")
