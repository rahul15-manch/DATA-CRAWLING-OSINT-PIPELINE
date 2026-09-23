"""
osint/providers/domain_intel_provider.py
========================================
SSL certificate and hosting infrastructure intelligence provider.
"""

import asyncio
from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus
from utils.domain_intel import get_domain_intel


class DomainIntelProvider(BaseOSINTProvider):
    name = "domain_intel"
    capability = ProviderCapability.DOMAIN_INTEL
    default_timeout = 3.5

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

        intel = await asyncio.to_thread(get_domain_intel, domain)
        ssl_valid = intel.get("ssl_valid", False)
        hosting_provider = intel.get("hosting_provider")

        data = {
            "domain_intel": intel,
            "ssl_valid": ssl_valid,
            "hosting_provider": hosting_provider,
        }

        evidence = {
            "target_domain": domain,
            "ssl_verified": ssl_valid,
        }

        status = ProviderStatus.SUCCESS if (ssl_valid or hosting_provider) else ProviderStatus.NO_RESULT

        return ProviderResult(
            provider=self.name,
            capability=self.capability,
            status=status,
            data=data,
            evidence=evidence,
        )
