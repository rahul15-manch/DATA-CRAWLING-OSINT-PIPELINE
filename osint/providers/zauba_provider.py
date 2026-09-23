"""
osint/providers/zauba_provider.py
================================
ZaubaCorp Indian corporate registry provider.
Wraps standalone registry_matching.py logic into the standard OSINT provider architecture.
"""

import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0"}


class ZaubaRegistryProvider(BaseOSINTProvider):
    name = "zauba_registry"
    capability = ProviderCapability.REGISTRY
    default_timeout = 6.0

    async def enrich(self, lead: LeadRecord) -> ProviderResult:
        company_name = (lead.company_name or "").strip()
        if not company_name or "?" in company_name or len(company_name.split()) > 6:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.NO_RESULT,
                data={},
                evidence={"reason": "invalid_or_article_name"},
            )

        encoded = quote_plus(company_name)
        url = f"https://www.zaubacorp.com/company-search/search?search={encoded}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=HEADERS, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = BeautifulSoup(html, "html.parser")
                        link = soup.find("a", href=lambda x: x and "/company/" in x)

                        if not link:
                            return ProviderResult(
                                provider=self.name,
                                capability=self.capability,
                                status=ProviderStatus.NO_RESULT,
                                data={},
                                evidence={"reason": "no_result_on_zaubacorp"},
                                source_urls=[url],
                            )

                        company_url = link.get("href")
                        company_name_found = link.get_text(strip=True)

                        data = {
                            "registered_name": company_name_found,
                            "registry_source": "ZaubaCorp",
                            "source_url": company_url,
                            "country": "IN",
                        }

                        return ProviderResult(
                            provider=self.name,
                            capability=self.capability,
                            status=ProviderStatus.SUCCESS,
                            data=data,
                            evidence={"matched_link": company_url},
                            source_urls=[url, company_url] if company_url else [url],
                        )
                    else:
                        return ProviderResult(
                            provider=self.name,
                            capability=self.capability,
                            status=ProviderStatus.ERROR,
                            error=f"ZaubaCorp HTTP {resp.status}",
                            source_urls=[url],
                        )
        except Exception as exc:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.ERROR,
                error=f"ZaubaCorp lookup error: {str(exc)}",
            )
