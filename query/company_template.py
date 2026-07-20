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
