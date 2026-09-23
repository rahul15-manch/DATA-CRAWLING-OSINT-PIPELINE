"""
models/lead_record.py
=====================
Canonical, strongly validated data contract for lead data across all
pipeline stages (Pillars 1–4).

Preserves identity, organization, contact, discovery, verification,
enrichment, provenance, and data quality information deterministically.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Unicode artifacts regex (e.g., leaked "\\u003e" in scraped emails)
UNICODE_ARTIFACT_RE = re.compile(r"^u00[0-9a-f]{2}", re.IGNORECASE)
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
PHONE_DIGITS_REGEX = re.compile(r"^\+?\d{7,15}$")


def normalize_domain(url_or_domain: Optional[str]) -> str:
    """Deterministically extracts clean registrable domain token."""
    if not url_or_domain:
        return ""
    val = url_or_domain.strip().lower()
    if "@" in val:
        val = val.split("@")[-1]
    if "://" in val:
        parsed = urlparse(val)
        val = parsed.netloc or val
    val = val.replace("www.", "").strip("/").split(":")[0]
    return val


class PersonRecord(BaseModel):
    """Canonical representation of a decision-maker or contact person."""
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    designation: Optional[str] = None
    linkedin: Optional[str] = None
    decision_maker_score: Optional[Union[int, float]] = None
    email: Optional[str] = None
    phone: Optional[str] = None

    @property
    def role(self) -> Optional[str]:
        return self.designation

    @model_validator(mode="before")
    @classmethod
    def handle_role_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "role" in data and "designation" not in data:
                data["designation"] = data["role"]
            elif "title" in data and "designation" not in data:
                data["designation"] = data["title"]
        return data

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        cleaned = re.sub(r"\s+", " ", v).strip()
        return cleaned or None



class LeadRecord(BaseModel):
    """
    Canonical Lead Record.

    Acts as the single source of truth across Discovery, Extraction,
    Cleaning, Verification, Enrichment, Finalization, ETL, and Database Export.
    """
    model_config = ConfigDict(extra="ignore")

    # ── Identity ──────────────────────────────────────────────
    id: Optional[Union[int, str]] = None
    company_name: str = Field(..., min_length=1)
    website: Optional[str] = None
    domain: Optional[str] = ""
    linkedin: Optional[str] = None
    company_type: Optional[str] = "Unknown"

    @field_validator("domain", mode="before")
    @classmethod
    def clean_domain_input(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    # ── Organization Metadata ─────────────────────────────────
    industry: Optional[str] = None
    location: Optional[str] = None
    country: Optional[str] = None
    employees: Optional[str] = None
    founded: Optional[str] = None
    description: Optional[str] = None
    tech_stack: List[str] = Field(default_factory=list)

    # ── Sub-pages ─────────────────────────────────────────────
    contact_page: Optional[str] = None
    about_page: Optional[str] = None
    team_page: Optional[str] = None

    # ── Contacts ──────────────────────────────────────────────
    emails: List[str] = Field(default_factory=list)
    phones: List[str] = Field(default_factory=list)
    social_links: Dict[str, str] = Field(default_factory=dict)
    people: List[PersonRecord] = Field(default_factory=list)
    email_candidates: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Discovery ─────────────────────────────────────────────
    source: Optional[str] = None
    source_url: Optional[str] = None
    keyword: Optional[str] = None
    discovered_at: Optional[str] = None

    # ── Verification ──────────────────────────────────────────
    verification_status: Optional[str] = None
    verified_emails: List[str] = Field(default_factory=list)
    verified_phones: List[str] = Field(default_factory=list)
    website_reachable: Optional[bool] = None
    domain_verification: Dict[str, Any] = Field(default_factory=dict)

    # ── Enrichment (Pillars 1 & 3) ─────────────────────────────
    domain_intel: Optional[Dict[str, Any]] = None
    lead_score: Optional[int] = None
    org_graph: Optional[Dict[str, Any]] = None
    emails_scored: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Provenance ────────────────────────────────────────────
    emails_provenance: List[Dict[str, Any]] = Field(default_factory=list)
    phones_provenance: List[Dict[str, Any]] = Field(default_factory=list)
    location_provenance: Optional[Dict[str, Any]] = None
    country_provenance: Optional[Dict[str, Any]] = None
    employees_provenance: Optional[Dict[str, Any]] = None
    founded_provenance: Optional[Dict[str, Any]] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)

    # ── Quality, Scoring & Telemetry ──────────────────────────
    confidence_score: Optional[Union[int, float]] = None
    confidence: Optional[float] = None
    lead_quality: Optional[str] = None
    relevance_score: Optional[Union[int, float]] = None
    relevance_tier: Optional[str] = None
    relevance_info: Dict[str, Any] = Field(default_factory=dict)
    data_quality: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    reason_if_rejected: Optional[str] = None
    created_at: Optional[str] = None

    # ── Extensibility (Provider-specific metadata) ────────────
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)

    # ── Normalization & Validation Hooks ──────────────────────

    @field_validator("industry")
    @classmethod
    def format_industry(cls, v: Optional[str]) -> Optional[str]:
        if not v or v.lower() == "unknown":
            return v
        v_clean = v.strip()
        return v_clean.upper() if len(v_clean) <= 3 else v_clean.title()

    @field_validator("emails")
    @classmethod
    def validate_emails(cls, v: List[str]) -> List[str]:
        valid_emails = []
        seen = set()
        for raw in v or []:
            if not isinstance(raw, str):
                continue
            email = raw.strip().lower()
            if UNICODE_ARTIFACT_RE.match(email):
                email = UNICODE_ARTIFACT_RE.sub("", email)
            if EMAIL_REGEX.match(email) and email not in seen:
                seen.add(email)
                valid_emails.append(email)
        return valid_emails

    @field_validator("phones")
    @classmethod
    def validate_phones(cls, v: List[str]) -> List[str]:
        valid_phones = []
        seen = set()
        for raw in v or []:
            if not isinstance(raw, str):
                continue
            cleaned = re.sub(r"[\s\-\(\)\.]", "", raw.strip())
            if PHONE_DIGITS_REGEX.match(cleaned) and cleaned not in seen:
                seen.add(cleaned)
                valid_phones.append(cleaned)
        return valid_phones

    @field_validator("tech_stack")
    @classmethod
    def dedupe_tech_stack(cls, v: List[str]) -> List[str]:
        seen = set()
        out = []
        for item in v or []:
            if isinstance(item, str) and item.strip() and item.strip() not in seen:
                seen.add(item.strip())
                out.append(item.strip())
        return out

    @model_validator(mode="after")
    def sync_and_normalize(self) -> LeadRecord:
        # 1. Normalize domain from website if empty
        if not self.domain and self.website:
            self.domain = normalize_domain(self.website)
        elif self.domain:
            self.domain = normalize_domain(self.domain)

        # 2. Synchronize confidence and confidence_score
        if self.confidence_score is not None and self.confidence is None:
            self.confidence = float(self.confidence_score)
        elif self.confidence is not None and self.confidence_score is None:
            self.confidence_score = self.confidence

        return self

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LeadRecord:
        """
        Constructs a LeadRecord from arbitrary pipeline dictionaries,
        handling legacy aliases and capturing unmodeled fields in extra_metadata.
        """
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data)}")

        item = dict(data)

        # Legacy company name aliases
        if "company_name" not in item and "company" in item:
            item["company_name"] = item["company"]

        # Ensure people items are normalized
        if "people" in item and isinstance(item["people"], list):
            parsed_people = []
            for p in item["people"]:
                if isinstance(p, PersonRecord):
                    parsed_people.append(p)
                elif isinstance(p, dict):
                    parsed_people.append(PersonRecord(**p))
            item["people"] = parsed_people

        # Handle known fields vs extra metadata
        known_fields = set(cls.model_fields.keys())
        extra = item.get("extra_metadata", {})
        if not isinstance(extra, dict):
            extra = {}

        filtered_data = {}
        for k, v in item.items():
            if k in known_fields:
                filtered_data[k] = v
            elif not k.startswith("_"):  # Keep non-internal extra fields
                extra[k] = v

        if extra:
            filtered_data["extra_metadata"] = extra

        return cls(**filtered_data)

    def to_dict(self, exclude_none: bool = False) -> Dict[str, Any]:
        """
        Serializes to a deterministic JSON-safe dictionary.
        """
        dump = self.model_dump(mode="json", exclude_none=exclude_none)
        # Ensure company alias exists for backward compatibility with legacy consumers
        dump["company"] = self.company_name
        return dump

    def to_flowiz_leads_row(self) -> Dict[str, Any]:
        """
        Formats record matching the `flowiz_leads` SQLite table schema.
        """
        import json
        return {
            "domain": self.domain or normalize_domain(self.website),
            "company_name": self.company_name,
            "website": self.website or "",
            "industry": self.industry or "",
            "location": self.location or "",
            "contact_page": self.contact_page or "",
            "about_page": self.about_page or "",
            "emails": json.dumps(self.emails),
            "phones": json.dumps(self.phones),
            "social_links": json.dumps(self.social_links),
            "people": json.dumps([p.model_dump() for p in self.people]),
            "tech_stack": json.dumps(self.tech_stack),
            "lead_score": self.lead_score,
            "description": self.description or "",
            "employees": self.employees or "",
            "founded": self.founded or "",
            "country": self.country or "",
            "domain_intel": json.dumps(self.domain_intel or {}),
            "org_graph": json.dumps(self.org_graph or {}),
        }

    def to_leads_row(self) -> Dict[str, Any]:
        """
        Formats record matching the `leads` SQLite table schema (api.py).
        """
        import json
        return {
            "company_name": self.company_name,
            "website": self.website or "",
            "linkedin": self.linkedin or "",
            "industry": self.industry or "",
            "location": self.location or "",
            "contact_page": self.contact_page or "",
            "about_page": self.about_page or "",
            "team_page": self.team_page or "",
            "emails": json.dumps(self.emails),
            "email_candidates": json.dumps(self.email_candidates),
            "phones": json.dumps(self.phones),
            "social_links": json.dumps(self.social_links),
            "people": json.dumps([p.model_dump() for p in self.people]),
            "company_type": self.company_type or "Unknown",
            "tech_stack": json.dumps(self.tech_stack),
            "description": self.description or "",
            "employees": self.employees or "",
            "founded": self.founded or "",
            "country": self.country or "",
            "confidence_score": self.confidence_score if self.confidence_score is not None else 0,
            "lead_quality": self.lead_quality or "Unknown",
            "keyword": self.keyword or "",
            "domain_intel": json.dumps(self.domain_intel or {}),
            "lead_score": self.lead_score,
            "org_graph": json.dumps(self.org_graph or {}),
        }
