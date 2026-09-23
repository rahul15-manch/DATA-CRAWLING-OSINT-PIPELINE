"""
osint/providers/social_provider.py
==================================
Social media profile discovery and company LinkedIn slug guessing provider.
Wraps standalone social_discovery.py into the canonical OSINT provider architecture.
"""

import aiohttp
import re
from bs4 import BeautifulSoup
from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus

SOCIAL_DOMAIN_PATTERNS = {
    "linkedin": re.compile(r"linkedin\.com/(company|in|school)/[A-Za-z0-9\-_.%]+", re.I),
    "twitter": re.compile(r"(?:twitter\.com|x\.com)/[A-Za-z0-9_]+", re.I),
    "facebook": re.compile(r"facebook\.com/[A-Za-z0-9.\-]+", re.I),
    "instagram": re.compile(r"instagram\.com/[A-Za-z0-9_.]+", re.I),
    "youtube": re.compile(r"youtube\.com/(channel|c|@)[A-Za-z0-9_\-]+", re.I),
}

LINK_JUNK = {
    "linkedin.com/company/linkedin",
    "twitter.com/intent",
    "x.com/intent",
    "facebook.com/sharer",
    "facebook.com/plugins",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FlowizSocialDiscovery/1.0)"}


def slugify_company_name(name: str) -> str:
    name = (name or "").lower()
    name = re.sub(r"\b(pvt|ltd|private|limited|inc|llp|technologies|technology|solutions|services|consulting|group)\b", "", name)
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return name


class SocialDiscoveryProvider(BaseOSINTProvider):
    name = "social_discovery"
    capability = ProviderCapability.SOCIAL
    default_timeout = 8.0

    async def _scan_page(self, session: aiohttp.ClientSession, url: str) -> dict:
        if not url:
            return {}
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            async with session.get(url, timeout=3.5, headers=HEADERS, allow_redirects=True) as resp:
                if resp.status < 400:
                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")
                    hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
                    haystack = hrefs + [html]
                    found = {}
                    for platform, pattern in SOCIAL_DOMAIN_PATTERNS.items():
                        for text in haystack:
                            m = pattern.search(text)
                            if m:
                                matched_url = m.group(0)
                                if any(junk in matched_url for junk in LINK_JUNK):
                                    continue
                                found[platform] = "https://" + matched_url.split("://")[-1]
                                break
                    return found
        except Exception:
            pass
        return {}

    async def enrich(self, lead: LeadRecord) -> ProviderResult:
        pages = [lead.website, lead.contact_page, lead.about_page, lead.team_page]
        pages_to_check = [p for p in pages if p]

        social_links = dict(lead.social_links or {})
        source_urls = []

        if pages_to_check:
            try:
                async with aiohttp.ClientSession() as session:
                    for page_url in pages_to_check:
                        source_urls.append(page_url)
                        found = await self._scan_page(session, page_url)
                        for platform, url in found.items():
                            if platform not in social_links:
                                social_links[platform] = url
                        if len(social_links) >= len(SOCIAL_DOMAIN_PATTERNS):
                            break
            except Exception:
                pass

        # Best-effort slug guess for LinkedIn if still missing
        slug_guess = None
        if "linkedin" not in social_links and lead.company_name:
            slug = slugify_company_name(lead.company_name)
            if slug:
                slug_guess = f"https://www.linkedin.com/company/{slug}"
                # Mark as guess in evidence, and attach if no official link found
                social_links["linkedin"] = slug_guess

        status = ProviderStatus.SUCCESS if social_links else ProviderStatus.NO_RESULT

        return ProviderResult(
            provider=self.name,
            capability=self.capability,
            status=status,
            data={"social_links": social_links},
            evidence={
                "found_platforms": list(social_links.keys()),
                "linkedin_is_slug_guess": bool(slug_guess and social_links.get("linkedin") == slug_guess),
            },
            source_urls=source_urls,
        )
