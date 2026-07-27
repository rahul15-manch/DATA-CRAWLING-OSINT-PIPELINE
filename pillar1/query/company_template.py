"""
query/company_template.py
=========================
Search source templates for company discovery.

Design rules
------------
1. The intent expansion layer handles generating business-intent keywords.
2. These templates only append the platform/source restriction.
3. Templates are fully generic — {keyword} is replaced by the expanded intent.
"""

COMPANY_TEMPLATES = [
    {
        "source": "google",
        "priority": 100,
        "templates": [
            "{keyword} {location}",
            "best {keyword} {location}",
            "top {keyword} {location}",
        ]
    },
    {
        "source": "linkedin",
        "priority": 90,
        "templates": [
            'site:linkedin.com/company "{keyword}"',
            'site:linkedin.com/company "{keyword}" {location}',
        ]
    },
    {
        "source": "clutch",
        "priority": 80,
        "templates": [
            'site:clutch.co "{keyword}" {location}',
            'site:clutch.co "{keyword}"',
        ]
    },
    {
        "source": "goodfirms",
        "priority": 70,
        "templates": [
            'site:goodfirms.co "{keyword}"',
            'site:goodfirms.co "{keyword}" {location}',
        ]
    },
    {
        "source": "github",
        "priority": 60,
        "templates": [
            'site:github.com "{keyword}" {location}',
        ]
    },
]

# Industry-aware semantic templates for domain B2B expansion
INDUSTRY_SEMANTIC_TEMPLATES = {
    "hardware_development": [
        "{concept} manufacturer",
        "{concept} OEM",
        "{concept} EMS company",
        "{concept} systems company",
        "{concept} assembly",
        "{concept} supplier",
        "{concept} contract manufacturer",
        "{concept} electronics company"
    ],
    "hardware_industrial": [
        "{concept} manufacturer",
        "{concept} supplier",
        "{concept} industrial distributor",
        "{concept} equipment manufacturer"
    ],
    "manufacturing": [
        "{concept} manufacturer",
        "{concept} OEM",
        "{concept} EMS company",
        "{concept} systems company",
        "{concept} assembly",
        "{concept} supplier",
        "{concept} contract manufacturer"
    ],
    "healthcare": [
        "{concept} medical devices",
        "{concept} digital health company",
        "{concept} healthtech startup",
        "{concept} clinical software",
        "{concept} EHR provider",
        "{concept} telemedicine company"
    ],
    "fintech": [
        "{concept} payment gateway",
        "{concept} banking platform",
        "{concept} fintech startup",
        "{concept} trading software",
        "{concept} ledger technology"
    ],
    "ai": [
        "{concept} AI startup",
        "{concept} machine learning lab",
        "{concept} LLM solutions provider",
        "{concept} computer vision company",
        "{concept} generative AI company"
    ],
    "logistics": [
        "{concept} freight forwarding",
        "{concept} supply chain solutions",
        "{concept} 3PL provider",
        "{concept} warehouse automation",
        "{concept} fleet tracking company"
    ],
    "retail": [
        "{concept} ecommerce platform",
        "{concept} D2C brand",
        "{concept} retail tech company",
        "{concept} omnichannel solutions"
    ],
    "construction": [
        "{concept} building materials manufacturer",
        "{concept} construction software",
        "{concept} HVAC manufacturer",
        "{concept} heavy equipment supplier"
    ]
}
