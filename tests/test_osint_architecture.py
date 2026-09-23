"""
tests/test_osint_architecture.py
================================
Milestone 4 OSINT Integration Architecture Test Suite.
Verifies provider contracts, registry, orchestrator execution, failure isolation,
timeout handling, deterministic result merging, evidence provenance, and built-in providers.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus
from osint.orchestrator import OSINTOrchestrator
from osint.registry import ProviderRegistry
from osint.providers import (
    WHOISProvider,
    DNSMXProvider,
    DomainIntelProvider,
    EmailVerificationProvider,
    HunterProvider,
    OpenCorporatesProvider,
    ZaubaRegistryProvider,
    SocialDiscoveryProvider,
    PhoneValidationProvider,
    DeepContactsProvider,
)


class MockSuccessProvider(BaseOSINTProvider):
    name = "mock_success"
    capability = ProviderCapability.DOMAIN_INTEL

    async def enrich(self, lead: LeadRecord) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            capability=self.capability,
            status=ProviderStatus.SUCCESS,
            data={"domain_intel": {"registrar": "MockRegistrar", "ssl_valid": True}},
            evidence={"source": "mock_source"},
            source_urls=["https://mock.test"],
        )


class MockFailingProvider(BaseOSINTProvider):
    name = "mock_failing"
    capability = ProviderCapability.REGISTRY

    async def enrich(self, lead: LeadRecord) -> ProviderResult:
        raise RuntimeError("Simulated external service disaster")


class MockTimeoutProvider(BaseOSINTProvider):
    name = "mock_timeout"
    capability = ProviderCapability.SOCIAL
    default_timeout = 0.05

    async def enrich(self, lead: LeadRecord) -> ProviderResult:
        await asyncio.sleep(0.5)
        return ProviderResult(
            provider=self.name,
            capability=self.capability,
            status=ProviderStatus.SUCCESS,
            data={"social_links": {"twitter": "https://x.com/late"}},
        )


class TestOSINTArchitecture(unittest.TestCase):
    def setUp(self):
        self.registry = ProviderRegistry()
        self.orchestrator = OSINTOrchestrator(registry=self.registry)

    # ── Test 1: Provider Contract ─────────────────────────────────────────
    def test_provider_result_contract(self):
        result = ProviderResult(
            provider="test_provider",
            capability=ProviderCapability.DOMAIN_INTEL,
            status=ProviderStatus.SUCCESS,
            data={"key": "value"},
            evidence={"signal": "strong"},
            source_urls=["https://test.io"],
            execution_time_ms=12.5,
        )
        self.assertEqual(result.provider, "test_provider")
        self.assertEqual(result.status, ProviderStatus.SUCCESS)
        self.assertTrue(result.is_successful)
        self.assertIn("key", result.data)
        self.assertIn("https://test.io", result.source_urls)

    # ── Test 2: Provider Registry ─────────────────────────────────────────
    def test_provider_registry_management(self):
        p1 = MockSuccessProvider()
        p2 = MockFailingProvider()
        self.registry.register(p1)
        self.registry.register(p2)

        self.assertIn("mock_success", self.registry.list_providers())
        self.assertIn("mock_failing", self.registry.list_providers())
        self.assertIs(self.registry.get("mock_success"), p1)

        domain_providers = self.registry.get_by_capability(ProviderCapability.DOMAIN_INTEL)
        self.assertEqual(len(domain_providers), 1)
        self.assertEqual(domain_providers[0].name, "mock_success")

        # Unregister
        removed = self.registry.unregister("mock_success")
        self.assertIs(removed, p1)
        self.assertNotIn("mock_success", self.registry.list_providers())

    # ── Test 3: Missing Configuration Handling ────────────────────────────
    def test_missing_configuration_handling(self):
        hunter = HunterProvider(api_key="")
        lead = LeadRecord(company_name="Acme", domain="acme.test")
        result = asyncio.run(hunter.run_safe(lead))

        self.assertEqual(result.status, ProviderStatus.CONFIGURATION_MISSING)
        self.assertFalse(result.is_successful)
        self.assertIn("HUNTER_API_KEY", result.evidence.get("reason", ""))

    # ── Test 4: Provider Timeout Isolation ────────────────────────────────
    def test_provider_timeout_isolation(self):
        timeout_p = MockTimeoutProvider(timeout=0.05)
        lead = LeadRecord(company_name="Acme", domain="acme.test")
        result = asyncio.run(timeout_p.run_safe(lead))

        self.assertEqual(result.status, ProviderStatus.TIMEOUT)
        self.assertIn("timed out", result.error.lower())

    # ── Test 5: Failure Isolation ─────────────────────────────────────────
    def test_orchestrator_failure_isolation(self):
        self.registry.register(MockSuccessProvider())
        self.registry.register(MockFailingProvider())

        lead = LeadRecord(company_name="Acme Corp", domain="acme.test")
        enriched = asyncio.run(self.orchestrator.enrich_lead(lead))

        # Successful provider data should be merged
        self.assertIsNotNone(enriched.domain_intel)
        self.assertEqual(enriched.domain_intel.get("registrar"), "MockRegistrar")

        # Failing provider should be isolated and recorded in evidence
        self.assertIn("osint_providers", enriched.evidence)
        failing_ev = enriched.evidence["osint_providers"].get("mock_failing")
        self.assertIsNotNone(failing_ev)
        self.assertEqual(failing_ev["status"], ProviderStatus.ERROR.value)
        self.assertIn("Simulated external service disaster", failing_ev["error"])

    # ── Test 6: Result Merging ────────────────────────────────────────────
    def test_result_merging_into_canonical_lead(self):
        self.registry.register(MockSuccessProvider())

        class MockSocialProvider(BaseOSINTProvider):
            name = "mock_social"
            capability = ProviderCapability.SOCIAL
            async def enrich(self, lead: LeadRecord) -> ProviderResult:
                return ProviderResult(
                    provider=self.name,
                    capability=self.capability,
                    status=ProviderStatus.SUCCESS,
                    data={"social_links": {"linkedin": "https://linkedin.com/company/acme", "twitter": "https://x.com/acme"}},
                )

        self.registry.register(MockSocialProvider())

        lead = LeadRecord(
            company_name="Acme Corp",
            domain="acme.test",
            emails=["existing@acme.test"],
            social_links={"facebook": "https://facebook.com/acme"}
        )

        enriched = asyncio.run(self.orchestrator.enrich_lead(lead))

        # Both providers merged
        self.assertEqual(enriched.domain_intel.get("registrar"), "MockRegistrar")
        self.assertEqual(enriched.social_links.get("facebook"), "https://facebook.com/acme")
        self.assertEqual(enriched.social_links.get("linkedin"), "https://linkedin.com/company/acme")
        self.assertEqual(enriched.social_links.get("twitter"), "https://x.com/acme")
        self.assertEqual(enriched.linkedin, "https://linkedin.com/company/acme")
        self.assertEqual(enriched.emails, ["existing@acme.test"])

    # ── Test 7: Preservation of M2 Canonical Fields ───────────────────────
    def test_preserves_canonical_fields(self):
        self.registry.register(MockSuccessProvider())

        lead = LeadRecord(
            company_name="Graph Integrity Inc",
            domain="graph.test",
            lead_score=87,
            org_graph={"company": "Graph Integrity", "node_count": 5},
            domain_intel={"existing_key": "preserved"},
        )

        enriched = asyncio.run(self.orchestrator.enrich_lead(lead))

        self.assertEqual(enriched.lead_score, 87)
        self.assertEqual(enriched.org_graph, {"company": "Graph Integrity", "node_count": 5})
        self.assertEqual(enriched.domain_intel.get("existing_key"), "preserved")
        self.assertEqual(enriched.domain_intel.get("registrar"), "MockRegistrar")

    # ── Test 8: Provenance Preservation ───────────────────────────────────
    def test_provenance_preservation(self):
        self.registry.register(MockSuccessProvider())
        lead = LeadRecord(company_name="Audit Co", domain="audit.test")
        enriched = asyncio.run(self.orchestrator.enrich_lead(lead))

        osint_ev = enriched.evidence.get("osint_providers", {})
        self.assertIn("mock_success", osint_ev)
        self.assertEqual(osint_ev["mock_success"]["status"], "SUCCESS")
        self.assertEqual(osint_ev["mock_success"]["source_urls"], ["https://mock.test"])
        self.assertIsNotNone(osint_ev["mock_success"]["retrieved_at"])

    # ── Test 9: Phone Validation Provider ─────────────────────────────────
    def test_phone_validation_provider(self):
        phone_p = PhoneValidationProvider()
        lead = LeadRecord(
            company_name="Phone Test",
            phones=["+1 650 253 0000", "080 1234 5678", "invalid-phone"]
        )
        result = asyncio.run(phone_p.run_safe(lead))
        self.assertEqual(result.status, ProviderStatus.SUCCESS)
        verified = result.data.get("verified_phones", [])
        self.assertIn("+16502530000", verified)

    # ── Test 10: Email Verifier Provider ──────────────────────────────────
    def test_email_verifier_provider(self):
        email_p = EmailVerificationProvider(enable_smtp_handshake=False)
        lead = LeadRecord(
            company_name="Email Test",
            emails=["valid@google.com", "not-an-email", "test@2x.png"]
        )
        result = asyncio.run(email_p.run_safe(lead))
        self.assertEqual(result.status, ProviderStatus.SUCCESS)
        valid = result.data.get("verified_emails", [])
        self.assertIn("valid@google.com", valid)
        self.assertNotIn("not-an-email", valid)
        self.assertNotIn("test@2x.png", valid)

    # ── Test 11: ZaubaCorp Registry Provider ──────────────────────────────
    def test_zauba_provider_article_filter(self):
        zauba_p = ZaubaRegistryProvider()
        lead = LeadRecord(company_name="What is Artificial Intelligence? A complete guide for students")
        result = asyncio.run(zauba_p.run_safe(lead))
        self.assertEqual(result.status, ProviderStatus.NO_RESULT)
        self.assertEqual(result.evidence.get("reason"), "invalid_or_article_name")

    # ── Test 12: Batch Lead Enrichment ────────────────────────────────────
    def test_batch_lead_enrichment(self):
        self.registry.register(MockSuccessProvider())
        leads = [
            LeadRecord(company_name=f"Batch Co {i}", domain=f"batch{i}.test")
            for i in range(5)
        ]
        enriched_leads = asyncio.run(self.orchestrator.enrich_leads(leads, concurrency=3))
        self.assertEqual(len(enriched_leads), 5)
        for el in enriched_leads:
            self.assertEqual(el.domain_intel.get("registrar"), "MockRegistrar")


if __name__ == "__main__":
    unittest.main()
