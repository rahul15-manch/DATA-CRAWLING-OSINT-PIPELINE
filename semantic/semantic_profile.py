"""
semantic/semantic_profile.py
============================
Dataclasses for IntentProfile and CompanyProfile in Flowiz.
"""

from dataclasses import dataclass, field
from typing import Set, List, Dict

@dataclass
class IntentProfile:
    primary_domain: str
    concepts: Set[str] = field(default_factory=set)
    positions: Set[str] = field(default_factory=set)
    services: Set[str] = field(default_factory=set)
    products: Set[str] = field(default_factory=set)
    confidence: float = 1.0
    ontology_version: str = "1.0.0"

    def to_dict(self) -> dict:
        return {
            "primary_domain": self.primary_domain,
            "concepts": list(self.concepts),
            "positions": list(self.positions),
            "services": list(self.services),
            "products": list(self.products),
            "confidence": self.confidence,
            "ontology_version": self.ontology_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'IntentProfile':
        return cls(
            primary_domain=data.get("primary_domain", "Unknown"),
            concepts=set(data.get("concepts", [])),
            positions=set(data.get("positions", [])),
            services=set(data.get("services", [])),
            products=set(data.get("products", [])),
            confidence=data.get("confidence", 1.0),
            ontology_version=data.get("ontology_version", "1.0.0"),
        )

@dataclass
class CompanyProfile:
    description: Dict[str, str] = field(default_factory=lambda: {"value": "", "source": "unknown"})
    services: List[Dict[str, str]] = field(default_factory=list)
    technologies: List[Dict[str, str]] = field(default_factory=list)
    products: List[Dict[str, str]] = field(default_factory=list)
    positions: List[Dict[str, str]] = field(default_factory=list)
    industries: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    partners: List[str] = field(default_factory=list)
    company_type: str = "Unknown"
    profile_confidence: float = 0.0
    sections: Dict[str, str] = field(default_factory=lambda: {
        "homepage": "",
        "about": "",
        "services": "",
        "careers": "",
        "blog": "",
        "products": ""
    })
    is_snippet: bool = False
    last_crawled: str = ""
    ontology_version: str = "1.0.0"
    website: str = ""
    website_source: str = ""

    def to_dict(self) -> dict:
        return {
            "is_snippet": self.is_snippet,
            "description": self.description,
            "services": self.services,
            "technologies": self.technologies,
            "products": self.products,
            "positions": self.positions,
            "industries": self.industries,
            "locations": self.locations,
            "certifications": self.certifications,
            "partners": self.partners,
            "company_type": self.company_type,
            "profile_confidence": self.profile_confidence,
            "sections": self.sections,
            "last_crawled": self.last_crawled,
            "ontology_version": self.ontology_version,
            "website": self.website,
            "website_source": self.website_source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CompanyProfile':
        return cls(
            is_snippet=data.get("is_snippet", False),
            description=data.get("description", {"value": "", "source": "unknown"}),
            services=data.get("services", []),
            technologies=data.get("technologies", []),
            products=data.get("products", []),
            positions=data.get("positions", []),
            industries=data.get("industries", []),
            locations=data.get("locations", []),
            certifications=data.get("certifications", []),
            partners=data.get("partners", []),
            company_type=data.get("company_type", "Unknown"),
            profile_confidence=data.get("profile_confidence", 0.0),
            sections=data.get("sections", {
                "homepage": "",
                "about": "",
                "services": "",
                "careers": "",
                "blog": "",
                "products": ""
            }),
            last_crawled=data.get("last_crawled", ""),
            ontology_version=data.get("ontology_version", "1.0.0"),
            website=data.get("website", ""),
            website_source=data.get("website_source", ""),
        )
