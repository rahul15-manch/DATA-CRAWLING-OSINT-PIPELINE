"""
osint/providers/whois_provider.py
=================================
WHOIS domain registration intelligence provider.
"""

import asyncio
import os
from typing import Any, Dict
from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus


class WHOISProvider(BaseOSINTProvider):
    name = "whois"
    capability = ProviderCapability.WHOIS
    default_timeout = 3.0

    def __init__(self, timeout: float = 3.0, enable_whois: bool = True):
        super().__init__(timeout=timeout)
        self.enabled = enable_whois and os.getenv("ENABLE_WHOIS", "true").lower() in ("true", "1", "yes")

    async def enrich(self, lead: LeadRecord) -> ProviderResult:
        domain = (lead.domain or "").strip()
        if not domain:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.NO_RESULT,
                data={},
                evidence={"reason": "no_domain_available"},
            )

        if not self.enabled:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.SKIPPED,
                data={},
                evidence={"reason": "whois_disabled_via_config"},
            )

        try:
            import whois
        except ImportError:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.NOT_AVAILABLE,
                data={},
                error="python-whois library not installed",
            )

        def _fetch_whois():
            try:
                return whois.whois(domain)
            except Exception as e:
                return {"error": str(e)}

        try:
            res = await asyncio.to_thread(_fetch_whois)
            if isinstance(res, dict) and "error" in res:
                return ProviderResult(
                    provider=self.name,
                    capability=self.capability,
                    status=ProviderStatus.NO_RESULT,
                    data={},
                    evidence={"error": res["error"]},
                )

            creation_date = getattr(res, "creation_date", None)
            if isinstance(creation_date, list):
                creation_date = creation_date[0]

            data = {
                "registrar": getattr(res, "registrar", None),
                "creation_date": str(creation_date) if creation_date else None,
                "country": getattr(res, "country", None),
                "org": getattr(res, "org", None),
            }

            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.SUCCESS if any(data.values()) else ProviderStatus.NO_RESULT,
                data=data,
                evidence={"raw_whois_available": True},
            )
        except Exception as e:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.ERROR,
                error=f"WHOIS lookup failed: {str(e)}",
            )
