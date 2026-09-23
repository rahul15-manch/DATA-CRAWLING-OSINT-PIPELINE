"""
osint/providers/deep_contacts_provider.py
=========================================
JSON-LD, Schema.org, and deep contact page crawler provider.
Integrates standalone osint_pipeline_fixed.py contact extraction.
"""

import aiohttp
import json
import re
from bs4 import BeautifulSoup
from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FlowizDeepContacts/1.0"}


class DeepContactsProvider(BaseOSINTProvider):
    name = "deep_contacts"
    capability = ProviderCapability.DEEP_CONTACTS
    default_timeout = 8.0

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

        extracted_data = {"emails": [], "phones": [], "schemas_found": []}
        base_url = f"https://{domain}"
        paths_to_check = ["", "/contact", "/about", "/contact-us"]
        source_urls = []

        email_pattern = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
        phone_pattern = re.compile(r'(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,5}\)?[\s\-]?)?\d{3,5}[\s\-]?\d{4,6}')

        try:
            async with aiohttp.ClientSession() as session:
                for path in paths_to_check:
                    target_url = base_url + path
                    source_urls.append(target_url)
                    try:
                        async with session.get(target_url, timeout=3.0, headers=HEADERS, allow_redirects=True) as resp:
                            if resp.status == 200:
                                html = await resp.text()
                                soup = BeautifulSoup(html, "html.parser")

                                # Extract JSON-LD / schema.org scripts
                                for script in soup.find_all("script", type="application/ld+json"):
                                    try:
                                        data = json.loads(script.string or "{}")
                                        if data:
                                            extracted_data["schemas_found"].append(data)
                                    except Exception:
                                        pass

                                # Extract text contacts
                                for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                                    tag.decompose()
                                clean_text = soup.get_text(separator=" ")

                                emails = [
                                    e.lower() for e in email_pattern.findall(clean_text)
                                    if not any(e.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".svg", ".webp", ".js", ".css"])
                                ]
                                phones = phone_pattern.findall(clean_text)

                                extracted_data["emails"].extend(emails)
                                extracted_data["phones"].extend([p.strip() for p in phones if len(p.strip()) >= 8])
                    except Exception:
                        continue
        except Exception as exc:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.ERROR,
                error=f"Deep contact scraping error: {str(exc)}",
                source_urls=source_urls,
            )

        extracted_data["emails"] = list(set(extracted_data["emails"]))
        extracted_data["phones"] = list(set(extracted_data["phones"]))

        has_data = bool(extracted_data["emails"] or extracted_data["phones"] or extracted_data["schemas_found"])
        status = ProviderStatus.SUCCESS if has_data else ProviderStatus.NO_RESULT

        return ProviderResult(
            provider=self.name,
            capability=self.capability,
            status=status,
            data=extracted_data,
            evidence={
                "schemas_count": len(extracted_data["schemas_found"]),
                "emails_found": len(extracted_data["emails"]),
                "phones_found": len(extracted_data["phones"]),
            },
            source_urls=source_urls,
        )
