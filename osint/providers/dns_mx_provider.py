"""
osint/providers/dns_mx_provider.py
==================================
DNS & Mail Exchange (MX) verification and email pattern candidate generator.
"""

import asyncio
from typing import List
from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus

_MX_CACHE = {}


class DNSMXProvider(BaseOSINTProvider):
    name = "dns_mx"
    capability = ProviderCapability.DNS_MX
    default_timeout = 3.0

    def _resolve_mx(self, domain: str) -> tuple[bool, List[str], str]:
        if domain in _MX_CACHE:
            return _MX_CACHE[domain]

        try:
            import dns.resolver
            answers = dns.resolver.resolve(domain, "MX", lifetime=self.timeout)
            hosts = [str(r.exchange).rstrip(".") for r in answers]
            res = (len(hosts) > 0, hosts, "ok" if hosts else "no_mx_records")
        except ImportError:
            res = (False, [], "dnspython_not_installed")
        except Exception as e:
            res = (False, [], f"dns_error:{type(e).__name__}")

        _MX_CACHE[domain] = res
        return res

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

        has_mx, hosts, reason = await asyncio.to_thread(self._resolve_mx, domain)

        candidate_emails = []
        if has_mx:
            prefixes = ["info", "contact", "hello", "sales", "support", "admin"]
            candidate_emails = [f"{p}@{domain}" for p in prefixes]

        data = {
            "has_mx": has_mx,
            "mx_hosts": hosts,
            "candidate_emails": candidate_emails,
        }

        evidence = {
            "resolution_status": reason,
            "mx_count": len(hosts),
        }

        return ProviderResult(
            provider=self.name,
            capability=self.capability,
            status=ProviderStatus.SUCCESS if has_mx else ProviderStatus.NO_RESULT,
            data=data,
            evidence=evidence,
        )
