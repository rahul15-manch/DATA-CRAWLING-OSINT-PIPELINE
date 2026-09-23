"""
osint/providers/opencorporates_provider.py
=========================================
OpenCorporates international corporate registry intelligence provider.
"""

import aiohttp
from urllib.parse import quote_plus
from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus


class OpenCorporatesProvider(BaseOSINTProvider):
    name = "opencorporates"
    capability = ProviderCapability.REGISTRY
    default_timeout = 6.0

    async def enrich(self, lead: LeadRecord) -> ProviderResult:
        company_name = (lead.company_name or "").strip()
        if not company_name or len(company_name) < 2:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.NO_RESULT,
                data={},
                evidence={"reason": "invalid_company_name"},
            )

        encoded_name = quote_plus(company_name)
        url = f"https://api.opencorporates.com/v0.7/companies/search?q={encoded_name}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        payload = await resp.json()
                        companies = payload.get("results", {}).get("companies", [])
                        if companies:
                            best = companies[0].get("company", {})
                            data = {
                                "registered_name": best.get("name"),
                                "jurisdiction_code": best.get("jurisdiction_code"),
                                "company_number": best.get("company_number"),
                                "status": best.get("current_status"),
                                "incorporation_date": best.get("incorporation_date"),
                                "registry_url": best.get("opencorporates_url"),
                            }
                            return ProviderResult(
                                provider=self.name,
                                capability=self.capability,
                                status=ProviderStatus.SUCCESS,
                                data=data,
                                evidence={
                                    "matched_company": best.get("name"),
                                    "source": "OpenCorporates API",
                                },
                                source_urls=[url],
                            )
                        return ProviderResult(
                            provider=self.name,
                            capability=self.capability,
                            status=ProviderStatus.NO_RESULT,
                            data={},
                            evidence={"reason": "no_matching_companies_found"},
                            source_urls=[url],
                        )
                    elif resp.status == 429:
                        return ProviderResult(
                            provider=self.name,
                            capability=self.capability,
                            status=ProviderStatus.RATE_LIMITED,
                            error="OpenCorporates rate limit reached",
                            source_urls=[url],
                        )
                    else:
                        return ProviderResult(
                            provider=self.name,
                            capability=self.capability,
                            status=ProviderStatus.ERROR,
                            error=f"OpenCorporates HTTP {resp.status}",
                            source_urls=[url],
                        )
        except Exception as exc:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.ERROR,
                error=f"OpenCorporates query failed: {str(exc)}",
            )
