"""
tests/test_canonical_contract.py
================================
Comprehensive tests for Milestone 2: Canonical Data Contract Implementation.
Validates LeadRecord, PersonRecord, PipelineResult integration,
normalization rules, enrichment preservation, provenance survival,
and SQLite database serialization for both `flowiz_leads` and `leads` tables.
"""

import json
import os
import sqlite3
import tempfile
import unittest

from models.lead_record import LeadRecord, PersonRecord, normalize_domain
from models.pipeline_result import PipelineResult


class TestCanonicalContract(unittest.TestCase):
    """Test suite verifying the canonical LeadRecord contract and invariants."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_leads.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── Test 1: Minimal Lead ───────────────────────────────────────────────
    def test_minimal_lead_validates(self):
        """A lead with only the minimum required fields validates and sets safe defaults."""
        lead = LeadRecord(company_name="Minimal Tech")
        self.assertEqual(lead.company_name, "Minimal Tech")
        self.assertEqual(lead.domain, "")
        self.assertEqual(lead.emails, [])
        self.assertEqual(lead.phones, [])
        self.assertEqual(lead.tech_stack, [])
        self.assertEqual(lead.people, [])
        self.assertIsNone(lead.website)
        self.assertIsNone(lead.domain_intel)
        self.assertIsNone(lead.lead_score)
        self.assertIsNone(lead.org_graph)

        # Must produce valid dictionary with backward-compatible company alias
        d = lead.to_dict()
        self.assertEqual(d["company_name"], "Minimal Tech")
        self.assertEqual(d["company"], "Minimal Tech")

    # ── Test 2: Full Enriched Lead ─────────────────────────────────────────
    def test_full_lead_validates(self):
        """A fully enriched lead with all sections validates completely."""
        lead = LeadRecord(
            company_name="Apex Global Inc",
            website="https://www.apex-global.com",
            linkedin="https://linkedin.com/company/apex-global",
            industry="enterprise saas",
            location="San Francisco, CA",
            country="US",
            employees="100-500",
            founded="2015",
            description="Enterprise process automation solutions.",
            tech_stack=["Python", "FastAPI", "React", "PostgreSQL"],
            contact_page="https://apex-global.com/contact",
            about_page="https://apex-global.com/about",
            team_page="https://apex-global.com/team",
            emails=["contact@apex-global.com", "sales@apex-global.com"],
            phones=["+1 (415) 555-0199"],
            social_links={"twitter": "https://twitter.com/apex", "github": "https://github.com/apex"},
            people=[
                PersonRecord(name="Alice Walker", designation="Chief Executive Officer", decision_maker_score=100),
                PersonRecord(name="Bob Vance", designation="VP Engineering", decision_maker_score=85),
            ],
            email_candidates=[{"email": "info@apex-global.com", "source": "domain_guess", "verified": False}],
            source="entity_resolution",
            source_url="https://apex-global.com",
            keyword="enterprise automation",
            verification_status="verified",
            verified_emails=["contact@apex-global.com"],
            verified_phones=["+14155550199"],
            website_reachable=True,
            domain_verification={"status": "verified", "evidence": "domain_match"},
            domain_intel={"tld": "com", "mx_valid": True, "registrar": "GoDaddy"},
            lead_score=92,
            org_graph={"nodes": 5, "edges": 4, "root": "Apex Global Inc"},
            emails_provenance=[{"fact": "contact@apex-global.com", "source": "contact_page", "verified": True}],
            phones_provenance=[{"fact": "+14155550199", "source": "footer", "verified": True}],
            confidence_score=95,
            lead_quality="High",
            relevance_score=90,
            relevance_tier="HIGH",
        )

        self.assertEqual(lead.domain, "apex-global.com")
        self.assertEqual(lead.industry, "Enterprise Saas")
        self.assertEqual(len(lead.people), 2)
        self.assertEqual(lead.lead_score, 92)
        self.assertEqual(lead.domain_intel["mx_valid"], True)
        self.assertEqual(lead.org_graph["nodes"], 5)
        self.assertEqual(lead.confidence, 95.0)

    # ── Test 3: Optional Enrichment ────────────────────────────────────────
    def test_optional_enrichment_does_not_invalidate(self):
        """Missing emails, phones, or enrichment data must not invalidate an otherwise valid lead."""
        data = {
            "company_name": "Discovery Target Corp",
            "website": "https://discovery-target.io",
            "source": "google_search",
        }
        lead = LeadRecord.from_dict(data)
        self.assertEqual(lead.company_name, "Discovery Target Corp")
        self.assertEqual(lead.domain, "discovery-target.io")
        self.assertEqual(lead.emails, [])
        self.assertEqual(lead.phones, [])
        self.assertEqual(lead.email_candidates, [])
        self.assertIsNone(lead.domain_intel)

    # ── Test 4: Deterministic Normalization ─────────────────────────────────
    def test_normalization_behavior(self):
        """Verify deterministic normalization for emails, phones, domains, and industry."""
        # Domain normalization
        self.assertEqual(normalize_domain("https://WWW.Example.COM/"), "example.com")
        self.assertEqual(normalize_domain("http://sub.domain.co.uk:8080/path?arg=1"), "sub.domain.co.uk")
        self.assertEqual(normalize_domain("user@company.io"), "company.io")

        # LeadRecord field validators
        lead = LeadRecord(
            company_name="Normalize Test",
            website="https://WWW.SampleCorp.NET/index.html",
            emails=["  test@samplecorp.net  ", "TEST@SAMPLECORP.NET", "u003einfo@samplecorp.net", "not-an-email"],
            phones=["(555) 123-4567", "+1-800-555-0199", "123"],  # '123' too short
            industry="it",
        )

        self.assertEqual(lead.domain, "samplecorp.net")
        # Deduplicated and normalized emails
        self.assertEqual(sorted(lead.emails), ["info@samplecorp.net", "test@samplecorp.net"])
        # Cleaned phones (only >= 7 digits)
        self.assertEqual(sorted(lead.phones), ["+18005550199", "5551234567"])
        # Short industry uppercase
        self.assertEqual(lead.industry, "IT")

    # ── Test 5: Serialization Round-Trip ───────────────────────────────────
    def test_serialization_round_trip(self):
        """LeadRecord -> dict/JSON -> LeadRecord preserves all values without data loss."""
        orig = LeadRecord(
            company_name="Roundtrip Systems",
            website="https://roundtrip.dev",
            industry="Cloud Computing",
            emails=["support@roundtrip.dev"],
            phones=["+15550001122"],
            tech_stack=["Docker", "Kubernetes"],
            people=[PersonRecord(name="Dev Leader", designation="Lead Architect")],
            domain_intel={"nameservers": ["ns1.cloudflare.com"]},
            lead_score=88,
            org_graph={"departments": ["R&D", "DevOps"]},
            emails_provenance=[{"url": "https://roundtrip.dev/contact"}],
            confidence_score=85,
        )

        serialized_dict = orig.to_dict()
        json_str = json.dumps(serialized_dict)
        restored_dict = json.loads(json_str)
        restored = LeadRecord.from_dict(restored_dict)

        self.assertEqual(restored.company_name, orig.company_name)
        self.assertEqual(restored.domain, orig.domain)
        self.assertEqual(restored.emails, orig.emails)
        self.assertEqual(restored.phones, orig.phones)
        self.assertEqual(restored.tech_stack, orig.tech_stack)
        self.assertEqual(restored.lead_score, orig.lead_score)
        self.assertEqual(restored.domain_intel, orig.domain_intel)
        self.assertEqual(restored.org_graph, orig.org_graph)
        self.assertEqual(restored.emails_provenance, orig.emails_provenance)
        self.assertEqual(restored.confidence_score, orig.confidence_score)

    # ── Test 6: Enrichment Preservation Across Stages ──────────────────────
    def test_enrichment_preservation(self):
        """Ensure domain_intel, lead_score, org_graph survive finalization & ETL."""
        raw_card = {
            "company_name": "Enrichment Keepers",
            "company": "Enrichment Keepers",
            "website": "https://keepers.org",
            "domain": "keepers.org",
            "emails": ["info@keepers.org"],
            "domain_intel": {"tld": "org", "safe": True},
            "lead_score": 90,
            "org_graph": {"entity_id": 1234},
            "_enrichment": {"discovered_emails": ["extra@keepers.org"]},
            "_verified_emails": ["info@keepers.org"],
            "_website_reachable": True,
        }

        # Step 5: Finalization
        from finalize_for_pillar4 import finalize_record
        finalized = finalize_record(dict(raw_card))
        self.assertEqual(finalized.get("domain_intel"), {"tld": "org", "safe": True})
        self.assertEqual(finalized.get("lead_score"), 90)
        self.assertEqual(finalized.get("org_graph"), {"entity_id": 1234})
        self.assertIn("extra@keepers.org", finalized.get("emails"))

        # Step 6: Pillar 4 ETL
        from pillar_4_pipeline.etl import ValidationPipeline, DeduplicationPipeline
        val_pipe = ValidationPipeline()
        cleaned_item = val_pipe(finalized)
        self.assertIsNotNone(cleaned_item)
        self.assertEqual(cleaned_item.get("domain_intel"), {"tld": "org", "safe": True})
        self.assertEqual(cleaned_item.get("lead_score"), 90)
        self.assertEqual(cleaned_item.get("org_graph"), {"entity_id": 1234})

        # Deduplication merge
        master_db = {}
        dedup_pipe = DeduplicationPipeline(master_db)
        dedup_pipe(cleaned_item)
        self.assertIn("keepers.org", master_db)
        self.assertEqual(master_db["keepers.org"]["lead_score"], 90)

    # ── Test 7: Provenance Preservation ────────────────────────────────────
    def test_provenance_preservation(self):
        """Fact-level provenance must survive card building, finalization, and ETL."""
        fact = {"value": "contact@provenance.org", "source_url": "https://provenance.org/contact", "observed": True}
        card = {
            "company_name": "Provenance Ltd",
            "website": "https://provenance.org",
            "emails": ["contact@provenance.org"],
            "emails_provenance": [fact],
            "phones_provenance": [{"value": "+15551234567", "source_url": "https://provenance.org"}],
            "data_quality": {"email": "observed"},
        }

        from finalize_for_pillar4 import finalize_record
        from pillar_4_pipeline.etl import ValidationPipeline

        finalized = finalize_record(card)
        self.assertEqual(finalized["emails_provenance"], [fact])

        val = ValidationPipeline()(finalized)
        self.assertIsNotNone(val)
        self.assertEqual(val["emails_provenance"], [fact])

    # ── Test 8: PipelineResult Integration ─────────────────────────────────
    def test_pipeline_result_integration(self):
        """PipelineResult seamlessly wraps and exposes LeadRecord objects."""
        lead1 = LeadRecord(company_name="Corp A", website="https://corpa.com")
        lead2_dict = {"company_name": "Corp B", "website": "https://corpb.com"}

        res = PipelineResult(
            records=[lead1, lead2_dict],
            raw_file="output/raw/test.json",
            record_count=2,
            status="success",
        )

        self.assertTrue(bool(res))
        self.assertEqual(len(res), 2)
        records = res.lead_records
        self.assertEqual(len(records), 2)
        self.assertIsInstance(records[0], LeadRecord)
        self.assertIsInstance(records[1], LeadRecord)
        self.assertEqual(records[0].domain, "corpa.com")
        self.assertEqual(records[1].domain, "corpb.com")

    # ── Test 9: Database Serialization (flowiz_leads & leads) ──────────────
    def test_database_serialization(self):
        """Verify canonical fields serialize to both active SQLite tables without loss."""
        lead = LeadRecord(
            company_name="Database Integrity Inc",
            website="https://db-integrity.com",
            linkedin="https://linkedin.com/company/db-integrity",
            industry="Data Analytics",
            location="New York, NY",
            emails=["data@db-integrity.com"],
            phones=["+12125550100"],
            people=[PersonRecord(name="Diana Prince", designation="Chief Data Officer")],
            tech_stack=["SQLite", "Python"],
            lead_score=99,
            domain_intel={"dns_sec": True},
            org_graph={"hierarchy": "parent"},
            confidence_score=94,
            lead_quality="High",
            keyword="database integrity",
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 1. Test flowiz_leads schema
        from pillar_4_pipeline.export import setup_database
        setup_database(cursor)
        row_flowiz = lead.to_flowiz_leads_row()
        cursor.execute("""
            INSERT OR REPLACE INTO flowiz_leads (
                domain, company_name, website, industry, location,
                contact_page, about_page, emails, phones, social_links, people,
                tech_stack, lead_score, description, employees, founded, country,
                domain_intel, org_graph
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row_flowiz["domain"], row_flowiz["company_name"], row_flowiz["website"],
            row_flowiz["industry"], row_flowiz["location"], row_flowiz["contact_page"],
            row_flowiz["about_page"], row_flowiz["emails"], row_flowiz["phones"],
            row_flowiz["social_links"], row_flowiz["people"], row_flowiz["tech_stack"],
            row_flowiz["lead_score"], row_flowiz["description"], row_flowiz["employees"],
            row_flowiz["founded"], row_flowiz["country"], row_flowiz["domain_intel"],
            row_flowiz["org_graph"],
        ))
        conn.commit()

        cur = cursor.execute("SELECT domain, company_name, lead_score, domain_intel, org_graph FROM flowiz_leads WHERE domain='db-integrity.com'")
        saved_f = cur.fetchone()
        self.assertIsNotNone(saved_f)
        self.assertEqual(saved_f[0], "db-integrity.com")
        self.assertEqual(saved_f[1], "Database Integrity Inc")
        self.assertEqual(saved_f[2], 99)
        self.assertEqual(json.loads(saved_f[3]), {"dns_sec": True})
        self.assertEqual(json.loads(saved_f[4]), {"hierarchy": "parent"})

        # 2. Test leads schema (api.py)
        import api
        orig_db = api.DB_PATH
        try:
            api.DB_PATH = self.db_path
            api.init_db()
            api._save_leads_to_db([lead.to_dict()], keyword="database integrity")
            res = api.get_leads()
            leads_saved = res.get("leads", [])
            self.assertEqual(len(leads_saved), 1)
            saved_l = leads_saved[0]
            self.assertEqual(saved_l["company_name"], "Database Integrity Inc")
            self.assertEqual(saved_l["lead_score"], 99)
            self.assertEqual(saved_l["domain_intel"], {"dns_sec": True})
            self.assertEqual(saved_l["org_graph"], {"hierarchy": "parent"})
        finally:
            api.DB_PATH = orig_db
            conn.close()

    # ── Test 10: Property / Invariant Testing ──────────────────────────────
    def test_property_invariants(self):
        """
        Verify key invariants:
        - No silent field loss: untransformed fields are identical.
        - Stable identity: domain and company_name remain stable.
        - Deterministic serialization: identical model produces identical dict.
        """
        initial_data = {
            "company_name": "Invariant Systems",
            "website": "https://invariant.io",
            "industry": "Formal Verification",
            "lead_score": 95,
            "custom_telemetry": "preserved_in_extra_metadata",
        }

        lead = LeadRecord.from_dict(initial_data)

        # Invariant 1: Stable Identity
        self.assertEqual(lead.domain, "invariant.io")
        self.assertEqual(lead.company_name, "Invariant Systems")

        # Invariant 2: Extra metadata preservation (no silent loss)
        self.assertIn("custom_telemetry", lead.extra_metadata)
        self.assertEqual(lead.extra_metadata["custom_telemetry"], "preserved_in_extra_metadata")

        # Invariant 3: Deterministic serialization
        dict_1 = lead.to_dict()
        dict_2 = lead.to_dict()
        self.assertEqual(dict_1, dict_2)
        self.assertEqual(dict_1["lead_score"], 95)
        self.assertEqual(dict_1["domain"], "invariant.io")


if __name__ == "__main__":
    unittest.main()
