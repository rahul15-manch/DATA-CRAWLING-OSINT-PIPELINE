"""
osint/orchestrator.py
=====================
Central orchestrator for executing OSINT providers with failure isolation,
concurrency control, and deterministic evidence merging into canonical LeadRecord.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union

from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus
from osint.registry import ProviderRegistry

logger = logging.getLogger(__name__)


class OSINTOrchestrator:
    """
    Coordinates modular OSINT intelligence collection across all registered providers.
    """

    def __init__(self, registry: Optional[ProviderRegistry] = None):
        self.registry = registry or ProviderRegistry()

    def register_provider(self, provider: BaseOSINTProvider) -> None:
        """Register a provider instance."""
        self.registry.register(provider)

    def list_providers(self) -> List[str]:
        """List names of registered providers."""
        return self.registry.list_providers()

    async def _execute_provider(self, provider: BaseOSINTProvider, lead: LeadRecord) -> ProviderResult:
        """Execute a single provider safely with failure isolation."""
        try:
            return await provider.run_safe(lead)
        except Exception as exc:
            logger.error(f"[OSINTOrchestrator] Unexpected failure in provider '{provider.name}': {exc}")
            return ProviderResult(
                provider=provider.name,
                capability=provider.capability,
                status=ProviderStatus.ERROR,
                error=f"Uncaught provider error: {str(exc)}",
            )

    def merge_result_into_lead(self, lead: LeadRecord, result: ProviderResult) -> None:
        """
        Deterministically merge a ProviderResult into the canonical LeadRecord.
        Preserves existing high-quality data and records audit evidence.
        """
        # 1. Record provider evidence for audit and provenance
        if not isinstance(lead.evidence, dict):
            lead.evidence = {}
        if "osint_providers" not in lead.evidence:
            lead.evidence["osint_providers"] = {}

        lead.evidence["osint_providers"][result.provider] = {
            "status": result.status.value,
            "capability": result.capability.value,
            "execution_time_ms": result.execution_time_ms,
            "retrieved_at": result.retrieved_at,
            "source_urls": result.source_urls,
            "evidence": result.evidence,
            "error": result.error,
        }

        if not result.is_successful:
            return

        data = result.data

        # 2. Merge capability-specific data without destructive overwrite
        if result.capability == ProviderCapability.DOMAIN_INTEL:
            intel = data.get("domain_intel") or {}
            if not lead.domain_intel:
                lead.domain_intel = {}
            for k, v in intel.items():
                if v is not None:
                    lead.domain_intel[k] = v

        elif result.capability == ProviderCapability.WHOIS:
            if not lead.domain_intel:
                lead.domain_intel = {}
            for field in ("registrar", "creation_date", "country", "org"):
                if data.get(field) and not lead.domain_intel.get(field):
                    lead.domain_intel[field] = data[field]

        elif result.capability == ProviderCapability.DNS_MX:
            candidates = data.get("candidate_emails") or []
            existing_cands = {c.get("email") for c in lead.email_candidates if isinstance(c, dict)}
            for cand in candidates:
                if cand not in existing_cands:
                    lead.email_candidates.append({
                        "email": cand,
                        "source": "dns_mx_pattern",
                        "verified": False,
                    })

        elif result.capability == ProviderCapability.EMAIL_VERIFICATION:
            new_verified = data.get("verified_emails") or []
            current_emails = set(lead.emails or [])
            for e in new_verified:
                if e and e not in current_emails:
                    lead.emails.append(e)
            lead.verified_emails = sorted(list(set(lead.verified_emails + new_verified)))

        elif result.capability == ProviderCapability.PHONE:
            new_phones = data.get("verified_phones") or []
            current_phones = set(lead.phones or [])
            for p in new_phones:
                if p and p not in current_phones:
                    lead.phones.append(p)
            lead.verified_phones = sorted(list(set(lead.verified_phones + new_phones)))

        elif result.capability == ProviderCapability.SOCIAL:
            social = data.get("social_links") or {}
            if not lead.social_links:
                lead.social_links = {}
            for platform, url in social.items():
                if url and platform not in lead.social_links:
                    lead.social_links[platform] = url
            if "linkedin" in social and not lead.linkedin:
                lead.linkedin = social["linkedin"]

        elif result.capability == ProviderCapability.REGISTRY:
            if not lead.extra_metadata:
                lead.extra_metadata = {}
            lead.extra_metadata["corporate_registry"] = data
            if data.get("country") and not lead.country:
                lead.country = data["country"]

        elif result.capability == ProviderCapability.DEEP_CONTACTS:
            deep_emails = data.get("emails") or []
            deep_phones = data.get("phones") or []
            schemas = data.get("schemas_found") or []

            current_emails = set(lead.emails or [])
            for e in deep_emails:
                if e and e not in current_emails:
                    lead.emails.append(e)

            current_phones = set(lead.phones or [])
            for p in deep_phones:
                if p and p not in current_phones:
                    lead.phones.append(p)

            if schemas:
                if not lead.extra_metadata:
                    lead.extra_metadata = {}
                lead.extra_metadata["json_ld_schemas"] = schemas

    async def enrich_lead(
        self,
        lead_input: Union[LeadRecord, Dict[str, Any]],
        provider_names: Optional[List[str]] = None,
    ) -> LeadRecord:
        """
        Enrich a single lead across registered providers.
        Executes non-dependent providers concurrently and safely merges results.
        """
        if isinstance(lead_input, dict):
            lead = LeadRecord.from_dict(lead_input)
        elif isinstance(lead_input, LeadRecord):
            lead = lead_input
        else:
            raise TypeError(f"Expected LeadRecord or dict, got {type(lead_input)}")

        providers_to_run = []
        if provider_names:
            for name in provider_names:
                p = self.registry.get(name)
                if p:
                    providers_to_run.append(p)
        else:
            providers_to_run = self.registry.get_all()

        if not providers_to_run:
            return lead

        # Run providers concurrently with failure isolation
        tasks = [self._execute_provider(p, lead) for p in providers_to_run]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, ProviderResult):
                self.merge_result_into_lead(lead, res)
            elif isinstance(res, Exception):
                logger.error(f"[OSINTOrchestrator] Task level failure during enrichment: {res}")

        return lead

    async def enrich_leads(
        self,
        leads: List[Union[LeadRecord, Dict[str, Any]]],
        concurrency: int = 5,
        provider_names: Optional[List[str]] = None,
    ) -> List[LeadRecord]:
        """
        Enrich a batch of leads with bounded concurrency.
        """
        if not leads:
            return []

        semaphore = asyncio.Semaphore(concurrency)

        async def _enrich_bounded(item):
            async with semaphore:
                return await self.enrich_lead(item, provider_names=provider_names)

        tasks = [_enrich_bounded(item) for item in leads]
        return await asyncio.gather(*tasks)
