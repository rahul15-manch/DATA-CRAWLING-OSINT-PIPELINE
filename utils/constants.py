"""
utils/constants.py
==================
Single source of truth for all Pillar 1 heuristics.

Every other module MUST import from here instead of defining its own sets.
This eliminates duplicated logic and makes updates instant across the whole
pipeline (Task 12 — code quality).
"""

# ── Domains that are NEVER a real business lead ───────────────────────────────

NON_COMPANY_DOMAINS = frozenset({
    # Education / college listing sites
    "collegedunia",
    "careers360",
    "shiksha",
    "getmyuni",
    "collegesearch",
    "engineering360",
    "entrancezone",
    "collegevidya",
    # Reference / Encyclopedia
    "wikipedia",
    "britannica",
    "investopedia",
    "encyclopedia",
    "merriam-webster",
    # Tutorial / E-Learning
    "geeksforgeeks",
    "tutorialspoint",
    "w3schools",
    "javatpoint",
    "coursera",
    "udemy",
    "edx",
    "khanacademy",
    "skillshare",
    "freecodecamp",
    "codecademy",
    "simplilearn",
    "pluralsight",
    "udacity",
    "nptel",
    "javatpoint",
    # Community / Q&A
    "quora",
    "reddit",
    "stackoverflow",
    "stackexchange",
    "zhihu",
    # Media / Blog / News
    "medium",
    "substack",
    "hashnode",
    "dev",              # dev.to
    "youtube",
    "youtu",
    "techcrunch",
    "theverge",
    "wired",
    "forbes",
    "businessinsider",
    "economictimes",
    "hindustantimes",
    "timesofindia",
    "businessstandard",
    "thehindu",
    "livemint",
    # Job boards
    "glassdoor",
    "indeed",
    "naukri",
    "shine",
    "ambitionbox",
    "linkedin",         # catch-all; specific company pages are OK via platform logic
    # Developer infrastructure
    "npmjs",
    "pypi",
    "github",
    # Review aggregators (listing pages, not the companies themselves)
    "g2",
    "capterra",
    "trustpilot",
    "getapp",
    # Indian B2C directories (listing pages, not companies)
    "sulekha",
    "indiamart",
    "tradeindia",
})

# ── Title terms that indicate informational / educational content ──────────────

INFORMATIONAL_TITLE_TERMS = frozenset({
    # Education
    "admission", "admissions",
    "college", "colleges",
    "university", "universities",
    "fees", "fee structure",
    "placement", "placements",
    "syllabus",
    "scholarship", "scholarships",
    "exam", "exams",
    "entrance",
    "cutoff", "cutoffs",
    # Learning / Content
    "tutorial", "tutorials",
    "course", "courses",
    "learn", "learning",
    "documentation", "docs",
    "guide", "guides",
    "examples", "example",
    "introduction",
    "beginner",
    "cheatsheet",
    "how to",
    "step by step",
    # Reference / Encyclopedic
    "wikipedia",
    "definition",
    "what is",
    "meaning",
    "overview",
    "history",
    "encyclopedia",
    "explained",
    "types of",
    # Media
    "blog",
    "news",
    "article",
    "magazine",
    "newsletter",
    "podcast",
    # Community
    "forum",
    "community",
    "discussion",
    "question", "questions",
    "answers", "answer",
    "faq",
    "thread",
    # Rankings / Comparison
    "ranking", "rankings",
    "top 10", "top 5", "top 7", "top 15", "top 20",
    "comparison",
    "best ",
    "vs ",
    "versus",
    "review", "reviews",
    # Jobs (not leads)
    "jobs", "job openings",
    "careers",
    "hiring",
    "vacancy", "vacancies",
    "internship",
})

# ── Keywords that strongly suggest a real business entity ─────────────────────

BUSINESS_HINTS = frozenset({
    "agency",
    "automation",
    "companies",
    "company",
    "consulting",
    "consultancy",
    "corp",
    "corporation",
    "enterprise",
    "enterprises",
    "firm",
    "firms",
    "group",
    "inc",
    "incorporated",
    "industrial",
    "industries",
    "limited",
    "llc",
    "ltd",
    "provider",
    "services",
    "software",
    "solutions",
    "startup",
    "systems",
    "technologies",
    "technology",
    "ventures",
})

# ── Platform / directory domains — they list companies but are NOT companies ──

PLATFORM_DOMAINS = frozenset({
    "linkedin.com",
    "clutch.co",
    "goodfirms.co",
    "justdial.com",
    "crunchbase.com",
    "wellfound.com",
    "angel.co",
    "apollo.io",
    "zoominfo.com",
    "yellowpages.com",
    "yelp.com",
    "indiamart.com",
    "tradeindia.com",
    "sulekha.com",
})

# ── Maps platform domain → human-readable source label ───────────────────────

SOURCE_DOMAIN_MAP = {
    "linkedin.com":    "LinkedIn",
    "clutch.co":       "Clutch",
    "goodfirms.co":    "GoodFirms",
    "justdial.com":    "Justdial",
    "crunchbase.com":  "Crunchbase",
    "wellfound.com":   "Wellfound",
    "angel.co":        "AngelList",
    "apollo.io":       "Apollo",
    "zoominfo.com":    "ZoomInfo",
}

# ── TLD whitelist for direct company websites ──────────────────────────────────

BUSINESS_DOMAIN_SUFFIXES = frozenset({
    "ai", "app", "biz", "co", "com", "in", "info", "io",
    "net", "org", "tech",
})

# ── Hard overrides: domain token → canonical company name ─────────────────────

DOMAIN_NAME_OVERRIDES = {
    "abb": "ABB",
    "adobe": "Adobe",
    "amazon": "Amazon",
    "automationanywhere": "Automation Anywhere",
    "aws": "AWS",
    "bosch": "Bosch",
    "freshworks": "Freshworks",
    "ge": "GE",
    "google": "Google",
    "hcl": "HCL",
    "hp": "HP",
    "ibm": "IBM",
    "infosys": "Infosys",
    "microsoft": "Microsoft",
    "openai": "OpenAI",
    "oracle": "Oracle",
    "rockwellautomation": "Rockwell Automation",
    "salesforce": "Salesforce",
    "sap": "SAP",
    "siemens": "Siemens",
    "tcs": "TCS",
    "uipath": "UiPath",
    "wipro": "Wipro",
    "zoho": "Zoho",
}

# ── Title segments from listing/platform sites that are noise ─────────────────

TITLE_NOISE_PARTS = frozenset({
    "ambitionbox",
    "capterra",
    "clutch",
    "crunchbase",
    "g2",
    "getapp",
    "glassdoor",
    "goodfirms",
    "indeed",
    "justdial",
    "linkedin",
    "naukri",
    "trustpilot",
    "zoominfo",
})

# ── Email priority order (index = rank; lower is better) ──────────────────────

EMAIL_PRIORITY_PREFIXES = [
    "founder",
    "ceo",
    "sales",
    "business",
    "partnership",
    "bd",
    "hello",
    "info",
    "contact",
    "support",
]

# ── Email local-part patterns to completely ignore ────────────────────────────

EMAIL_IGNORE_PATTERNS = frozenset({
    "noreply",
    "no-reply",
    "no_reply",
    "donotreply",
    "do-not-reply",
    "bounce",
    "bounces",
    "unsubscribe",
    "notification",
    "notifications",
    "tracking",
    "newsletter",
    "mailer",
    "maildaemon",
    "mail-daemon",
    "postmaster",
    "marketing",
    "automated",
    "system",
    "alert",
    "alerts",
    "webmaster",
})

# ── Designation keywords for decision-maker extraction ────────────────────────

DESIGNATION_KEYWORDS = [
    "founder",
    "co-founder",
    "cofounder",
    "ceo",
    "cto",
    "coo",
    "cfo",
    "cmo",
    "director",
    "managing director",
    "president",
    "vice president",
    "vp",
    "head of",
    "partner",
    "managing partner",
    "chairman",
    "chairperson",
]

# ── Designations that should be uppercased in output ─────────────────────────

DESIGNATION_ACRONYMS = frozenset({
    "ceo", "cto", "coo", "cfo", "cmo", "vp", "md",
})

# ── Tokens that cannot be part of a real person name ──────────────────────────

PERSON_NAME_NOISE_WORDS = frozenset({
    # Certificates / Courses
    "certificate", "certification", "course", "degree", "diploma",
    "training", "workshop", "program", "bootcamp", "module",
    # Institutions
    "college", "university", "institute", "academy", "school", "campus",
    # Content types
    "blog", "article", "guide", "tutorial", "documentation",
    "introduction", "overview", "review", "ranking", "comparison",
    # Sentence fragments
    "what is", "how to", "learn", "admission", "placement", "fees",
    "recommendation", "recommendations",
    # Technical domains (when used as standalone 2-word "names")
    "engineering", "technology", "management", "science",
    "artificial intelligence", "machine learning",
    # Address / structural fragments
    "address", "registered", "corporate", "communications",
    "floor", "building", "street", "office",
})

# ── Quality penalty weights ───────────────────────────────────────────────────

QUALITY_PENALTIES = {
    "wikipedia":   40,
    "college":     30,
    "university":  30,
    "admission":   30,
    "fees":        30,
    "placement":   30,
    "ranking":     30,
    "rankings":    30,
    "blog":        25,
    "tutorial":    25,
    "course":      25,
    "documentation": 25,
    "news":        20,
    "magazine":    20,
    "forum":       20,
    "community":   15,
}

# ── Threshold for hard-rejecting a lead (vs. Low-quality label) ───────────────

HARD_REJECT_PENALTY_THRESHOLD = 40


# ─────────────────────────────────────────────────────────────────────────────
# Task 4 — Source Confidence Scores
# ─────────────────────────────────────────────────────────────────────────────

SOURCE_CONFIDENCE_SCORES = {
    "official website": 100,
    "linkedin":         95,
    "crunchbase":       90,
    "clutch":           90,
    "goodfirms":        85,
    "wellfound":        85,
    "angellist":        85,
    "apollo":           80,
    "zoominfo":         80,
    "justdial":         75,
    "directory":        75,
    "google":           70,
    "blog":             20,
    "wikipedia":        0,
    "tutorial":         0,
}

# Default score for unknown sources
DEFAULT_SOURCE_SCORE = 70


# ─────────────────────────────────────────────────────────────────────────────
# Task 6 — Company Type Keywords
# ─────────────────────────────────────────────────────────────────────────────

COMPANY_TYPE_KEYWORDS = {
    "AI Startup": [
        "artificial intelligence", "machine learning", "deep learning",
        "llm", "generative ai", "neural network", "nlp",
    ],
    "Software Company": [
        "saas", "software", "platform", "cloud", "app", "application",
        "erp", "crm", "devops", "api",
    ],
    "Consultancy": [
        "consulting", "consultancy", "advisory", "management consulting",
        "strategy consulting",
    ],
    "Agency": [
        "agency", "creative agency", "marketing agency", "digital agency",
        "advertising agency",
    ],
    "Manufacturer": [
        "manufacturer", "manufacturing", "production", "fabrication",
        "oem", "factory",
    ],
    "Industrial": [
        "industrial", "automation", "robotics", "plc", "scada",
        "engineering", "heavy industry",
    ],
    "Healthcare": [
        "healthcare", "hospital", "medical", "pharma", "pharmaceutical",
        "clinical", "biotech", "medtech",
    ],
    "Finance": [
        "financial", "fintech", "banking", "insurance", "investment",
        "payment", "trading", "wealth",
    ],
    "Marketplace": [
        "marketplace", "ecommerce", "e-commerce", "retail", "store",
        "shop", "b2b marketplace",
    ],
    "Telecom": [
        "telecom", "telecommunications", "network", "connectivity",
        "broadband", "wireless",
    ],
    "Construction": [
        "construction", "infrastructure", "civil", "real estate",
        "architecture", "contractor",
    ],
    "Legal": [
        "law firm", "legal", "attorney", "solicitor", "compliance",
    ],
    "Education Company": [
        "edtech", "e-learning", "lms", "learning management", "online education",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Task 7 — Industry Detection Keywords
# ─────────────────────────────────────────────────────────────────────────────

INDUSTRY_KEYWORD_MAP = {
    "Artificial Intelligence": [
        "ai", "artificial intelligence", "machine learning", "deep learning",
        "llm", "generative", "neural network", "natural language processing",
        "computer vision",
    ],
    "Industrial Automation": [
        "automation", "rpa", "robotic process", "industrial automation",
        "plc", "scada", "hmi", "dcs", "iot", "iiot",
    ],
    "Mechanical Engineering": [
        "mechanical engineering", "mechanical", "hvac", "thermal",
        "fluid dynamics", "manufacturing engineering",
    ],
    "Civil Engineering": [
        "civil engineering", "infrastructure", "structural", "construction",
        "geotechnical", "transportation",
    ],
    "Software Development": [
        "software development", "app development", "web development",
        "devops", "agile", "full stack", "backend", "frontend",
    ],
    "Cloud Computing": [
        "cloud", "aws", "azure", "gcp", "saas", "paas", "iaas",
        "kubernetes", "docker",
    ],
    "Cybersecurity": [
        "cybersecurity", "security", "infosec", "soc", "penetration testing",
        "firewall", "compliance",
    ],
    "Healthcare": [
        "healthcare", "medical", "pharma", "hospital", "clinical",
        "biotech", "medtech", "health tech",
    ],
    "Finance": [
        "fintech", "banking", "financial services", "insurance",
        "investment", "payment processing",
    ],
    "Electrical Engineering": [
        "electrical engineering", "power systems", "semiconductor",
        "electronics", "embedded systems",
    ],
    "Chemical Engineering": [
        "chemical engineering", "process engineering", "petrochemical",
        "polymer", "refinery",
    ],
    "Logistics": [
        "logistics", "supply chain", "shipping", "warehouse", "freight",
        "last mile",
    ],
    "EdTech": [
        "edtech", "e-learning", "online learning", "lms",
        "education technology",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Task 8 — Decision Maker Ranking Scores
# ─────────────────────────────────────────────────────────────────────────────

DECISION_MAKER_SCORES = {
    "founder":             100,
    "co-founder":          95,
    "cofounder":           95,
    "ceo":                 90,
    "managing director":   85,
    "president":           85,
    "cto":                 80,
    "coo":                 75,
    "cfo":                 70,
    "cmo":                 68,
    "director":            70,
    "vice president":      65,
    "vp":                  65,
    "head of":             60,
    "managing partner":    60,
    "partner":             55,
    "chairman":            85,
    "chairperson":         85,
    "business development": 60,
    "hr":                  40,
    "recruiter":           30,
    "support":             20,
}


# ─────────────────────────────────────────────────────────────────────────────
# Task 11 — Company Name Normalization
# ─────────────────────────────────────────────────────────────────────────────

COMPANY_LEGAL_SUFFIXES = frozenset({
    "inc", "incorporated",
    "ltd", "limited",
    "llc",
    "corp", "corporation",
    "co",
    "plc",
    "pvt",
    "gmbh",
    "ag",
    "sa",
    "bv",
})

COMPANY_GEOGRAPHIC_QUALIFIERS = frozenset({
    "india", "india pvt",
    "international",
    "global",
    "worldwide",
    "americas", "america",
    "europe", "european",
    "asia", "asian",
    "apac",
})


# ─────────────────────────────────────────────────────────────────────────────
# Government Domain Blocklist
# ─────────────────────────────────────────────────────────────────────────────
# Any URL whose domain ends with one of these suffixes is rejected as a lead.
# Government portals are NOT B2B/B2C companies.

GOVERNMENT_DOMAIN_SUFFIXES = frozenset({
    ".gov",
    ".gov.in",
    ".gov.uk",
    ".gov.au",
    ".gov.us",
    ".gov.ca",
    ".nic.in",       # India national informatics centre
    ".gov.sg",
    ".govt.nz",
})


# ─────────────────────────────────────────────────────────────────────────────
# Forum Domain Blocklist
# ─────────────────────────────────────────────────────────────────────────────
# Substrings checked against the netloc of a URL.
# If any of these appear in the hostname the result is rejected.

FORUM_DOMAIN_BLOCKLIST = frozenset({
    "reddit.com",
    "quora.com",
    "stackoverflow.com",
    "stackexchange.com",
    "zhihu.com",
    "medium.com",
    "dev.to",
    "hashnode.dev",
    "hackernews.com",
    "news.ycombinator.com",
})


# ─────────────────────────────────────────────────────────────────────────────
# Article Author Prefix Stripping
# ─────────────────────────────────────────────────────────────────────────────
# If a scraped "name" starts with one of these prefixes it is an article
# byline, not a person name.  Strip the prefix before validation.

ARTICLE_AUTHOR_PREFIXES = (
    "written by ",
    "posted by ",
    "published by ",
    "author: ",
    "author ",
    "by ",
)
