"""
osint/models.py
===============
Structured result models and status definitions for the OSINT provider architecture.
Guarantees consistent, type-safe evidence collection across all external intelligence sources.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class ProviderStatus(str, Enum):
    """Execution status of an OSINT provider operation."""
    SUCCESS = "SUCCESS"
    NO_RESULT = "NO_RESULT"
    SKIPPED = "SKIPPED"
    CONFIGURATION_MISSING = "CONFIGURATION_MISSING"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class ProviderCapability(str, Enum):
    """Categorized capability offered by an OSINT provider."""
    DOMAIN_INTEL = "DOMAIN_INTEL"
    WHOIS = "WHOIS"
    DNS_MX = "DNS_MX"
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
    SMTP_VERIFICATION = "SMTP_VERIFICATION"
    REGISTRY = "REGISTRY"
    SOCIAL = "SOCIAL"
    PHONE = "PHONE"
    DEEP_CONTACTS = "DEEP_CONTACTS"
    CUSTOM = "CUSTOM"


class ProviderResult(BaseModel):
    """
    Canonical result contract returned by every OSINT provider.
    Provides complete provenance and evidence tracking.
    """
    model_config = ConfigDict(extra="ignore")

    provider: str = Field(..., description="Unique provider identifier, e.g. 'whois', 'opencorporates'")
    capability: ProviderCapability = Field(..., description="Primary capability of the provider")
    status: ProviderStatus = Field(..., description="Execution outcome status")
    data: Dict[str, Any] = Field(default_factory=dict, description="Extracted structured facts/attributes")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Raw evidence, signals, or audit metadata")
    source_urls: List[str] = Field(default_factory=list, description="Target URLs consulted during enrichment")
    retrieved_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp of retrieval"
    )
    execution_time_ms: float = Field(0.0, description="Measured execution duration in milliseconds")
    error: Optional[str] = Field(None, description="Error message if status is ERROR, TIMEOUT, etc.")

    @property
    def is_successful(self) -> bool:
        """Helper to quickly check if provider retrieved usable data."""
        return self.status == ProviderStatus.SUCCESS and bool(self.data)
