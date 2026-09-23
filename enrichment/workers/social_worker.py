"""Adapter for existing social-link extraction."""

import re
from urllib.parse import urlparse

from enrichment.contracts import CompanyContext, WorkerResult


class SocialWorker:
    name = "social"
    priority = 3

    @staticmethod
    def should_run(context: CompanyContext) -> bool:
        return not bool((context.baseline_extraction or {}).get("social_links"))

    def run(self, context: CompanyContext) -> WorkerResult:
        extracted = context.baseline_extraction or {}
        social_links = dict(extracted.get("social_links") or {})
        provenance = {}
        token = re.sub(r"[^a-z0-9]", "", (context.domain or context.company_name).lower())
        for platform, url in list(social_links.items()):
            url_token = re.sub(r"[^a-z0-9]", "", urlparse(url).path.lower())
            provenance[platform] = {
                "platform": platform,
                "url": url,
                "source": "homepage_link",
                "verified": bool(token and token in url_token),
            }
        if not social_links and context.search and context.company_name:
            import config
            if getattr(config, "SERPAPI_PRIMARY_MODE", False):
                query = f'site:linkedin.com/company "{context.company_name}"'
                for result in context.cached_search(query, max_results=3):
                    url = result.get("url", "")
                    if "linkedin.com/company/" in url.lower():
                        social_links["linkedin"] = url
                        provenance["linkedin"] = {
                            "platform": "linkedin",
                            "url": url,
                            "source": "SerpApi snippet",
                            "verified": True,
                        }
                        print(f"[SERPAPI] SOCIAL: linkedin='{url}' source=SerpApi snippet")
                        break
        return WorkerResult(
            worker_name=self.name,
            fields={"social_links": social_links},
            provenance={"social_links": provenance},
            missing_fields=["social_links"] if not social_links else [],
            metadata={"verified": False},
        )
