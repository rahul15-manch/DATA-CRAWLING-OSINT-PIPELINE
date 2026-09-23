"""
osint/providers/hunter_provider.py
==================================
Hunter.io email discovery and pattern intelligence provider.
"""

import os
import aiohttp
import config
from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus


class HunterProvider(BaseOSINTProvider):
    name = "hunter"
    capability = ProviderCapability.EMAIL_VERIFICATION
    default_timeout = 6.0

    def __init__(self, api_key: str = None, timeout: float = 6.0, enabled: bool = None):
        super().__init__(timeout=timeout)
        self.api_key = api_key if api_key is not None else os.getenv("HUNTER_API_KEY", "")
        if enabled is not None:
            self.enabled = bool(enabled)
        elif api_key is not None:
            # Caller explicitly passed api_key parameter (e.g., testing config handling)
            self.enabled = True
        else:
            self.enabled = bool(getattr(config, "HUNTER_ENABLED", False))

    async def enrich(self, lead: LeadRecord) -> ProviderResult:
        # Milestone 5: Hunter is DEFERRED by default (API credentials unavailable)
        if not self.enabled:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.SKIPPED,
                data={},
                evidence={"reason": "DEFERRED — API credentials unavailable", "hunter_enabled": False},
            )

        if not self.api_key or "YOUR_HUNTER_API_KEY" in self.api_key:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.CONFIGURATION_MISSING,
                data={},
                evidence={"reason": "HUNTER_API_KEY environment variable not set"},
            )

        domain = (lead.domain or "").strip()
        if not domain:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.NO_RESULT,
                data={},
                evidence={"reason": "no_domain_available"},
            )

        url = "https://api.hunter.io/v2/domain-search"
        params = {"domain": domain, "api_key": self.api_key}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        payload = await resp.json()
                        hunter_data = payload.get("data", {})
                        emails = [e["value"] for e in hunter_data.get("emails", []) if "value" in e]
                        pattern = hunter_data.get("pattern")
                        
                        return ProviderResult(
                            provider=self.name,
                            capability=self.capability,
                            status=ProviderStatus.SUCCESS if emails else ProviderStatus.NO_RESULT,
                            data={"emails": emails, "pattern": pattern},
                            evidence={"total_hunter_emails": len(emails), "pattern": pattern},
                            source_urls=[url],
                        )
                    elif resp.status in (401, 403):
                        return ProviderResult(
                            provider=self.name,
                            capability=self.capability,
                            status=ProviderStatus.CONFIGURATION_MISSING,
                            error=f"Hunter API authentication failed: HTTP {resp.status}",
                        )
                    elif resp.status == 429:
                        return ProviderResult(
                            provider=self.name,
                            capability=self.capability,
                            status=ProviderStatus.RATE_LIMITED,
                            error="Hunter API rate limit exceeded",
                        )
                    else:
                        return ProviderResult(
                            provider=self.name,
                            capability=self.capability,
                            status=ProviderStatus.ERROR,
                            error=f"Hunter API returned HTTP {resp.status}",
                        )
        except Exception as exc:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.ERROR,
                error=f"Hunter query failed: {str(exc)}",
            )
