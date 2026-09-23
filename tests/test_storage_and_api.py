"""
tests/test_storage_and_api.py
=============================
Milestone 3 Verification Test Suite:
1. Canonical database schema initialization & idempotency
2. Repository creation (upsert_lead, bulk_upsert_leads)
3. Repository retrieval (get_lead_by_domain, get_leads, get_all_leads)
4. Canonical round-trip preservation: LeadRecord -> SQLite -> LeadRecord
5. Enrichment preservation: domain_intel, lead_score, org_graph
6. Provenance & metadata preservation in canonical storage
7. API read from canonical flowiz_leads
8. API response contract preservation (lead_score, domain_intel, org_graph)
9. Legacy storage protection & coexistence
10. Database path resolution consistency across pipeline, repository, and API
11. Migration safety & idempotency from legacy leads to canonical flowiz_leads
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from database.connection import get_db_connection, setup_database, get_db_path, get_default_db_path
from database.repository import LeadRepository, row_to_lead_record
from models.lead_record import LeadRecord, PersonRecord


class TestCanonicalStorageAndAPI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_leads.db")
        self.repo = LeadRepository(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    # ── Test 1: Canonical Database Initialization ─────────────────────────
    def test_canonical_database_initialization(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='flowiz_leads'")
        self.assertIsNotNone(cur.fetchone(), "flowiz_leads table must exist")

        cur.execute("PRAGMA table_info(flowiz_leads)")
        columns = {row[1] for row in cur.fetchall()}
        required_cols = {
            "domain", "company_name", "website", "industry", "location",
            "contact_page", "about_page", "emails", "phones", "social_links",
            "people", "tech_stack", "lead_score", "description", "employees",
            "founded", "country", "domain_intel", "org_graph",
            "confidence_score", "lead_quality", "keyword"
        }
        missing = required_cols - columns
        self.assertEqual(len(missing), 0, f"Missing canonical columns: {missing}")
        conn.close()

    # ── Test 2: Repository Create (Upsert) ─────────────────────────────────
    def test_repository_create_lead(self):
        lead = LeadRecord(
            company_name="Apex AI Technologies",
            domain="apexai.test",
            website="https://apexai.test",
            industry="Artificial Intelligence",
            lead_score=95,
            emails=["contact@apexai.test"],
            phones=["+1-555-0199"],
            domain_intel={"dns_sec": True, "registrar": "TestReg"},
            org_graph={"nodes": [{"id": "apexai.test"}], "edges": []},
            confidence_score=92.5,
            lead_quality="High",
            keyword="ai tools",
        )
        saved = self.repo.upsert_lead(lead)
        self.assertEqual(saved.domain, "apexai.test")

        # Verify directly in SQLite
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT domain, company_name, lead_score FROM flowiz_leads WHERE domain='apexai.test'")
        row = cur.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "apexai.test")
        self.assertEqual(row[1], "Apex AI Technologies")
        self.assertEqual(row[2], 95)

    # ── Test 3: Repository Read ───────────────────────────────────────────
    def test_repository_read_lead(self):
        lead = LeadRecord(
            company_name="Nexus Cloud",
            domain="nexuscloud.test",
            website="https://nexuscloud.test",
            industry="Cloud Computing",
            lead_score=88,
            emails=["info@nexuscloud.test"],
            tech_stack=["Kubernetes", "AWS", "FastAPI"],
        )
        self.repo.upsert_lead(lead)

        fetched = self.repo.get_lead_by_domain("nexuscloud.test")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.company_name, "Nexus Cloud")
        self.assertEqual(fetched.industry, "Cloud Computing")
        self.assertEqual(fetched.lead_score, 88)
        self.assertIn("Kubernetes", fetched.tech_stack)

    # ── Test 4: Canonical Round-Trip ──────────────────────────────────────
    def test_round_trip_preservation(self):
        original = LeadRecord(
            company_name="RoundTrip Robotics",
            domain="rtrobotics.test",
            website="https://rtrobotics.test",
            linkedin="https://linkedin.com/company/rtrobotics",
            industry="Robotics",
            location="San Jose, CA",
            country="United States",
            founded="2018",
            employees="100-250",
            description="Autonomous warehousing robotics.",
            emails=["founders@rtrobotics.test", "sales@rtrobotics.test"],
            phones=["14085550123"],
            social_links={"twitter": "https://x.com/rtrobotics"},
            people=[
                PersonRecord(name="Dr. Jane Doe", role="CTO", email="jane@rtrobotics.test"),
                PersonRecord(name="John Smith", role="CEO", email="john@rtrobotics.test"),
            ],
            tech_stack=["ROS2", "Python", "C++", "PyTorch"],
            lead_score=97,
            domain_intel={"whois_age_days": 1825, "ip": "1.2.3.4"},
            org_graph={"executives": ["Jane Doe", "John Smith"]},
            confidence_score=94.0,
            lead_quality="High",
            keyword="robotics automation",
        )

        self.repo.upsert_lead(original)
        loaded = self.repo.get_lead_by_domain("rtrobotics.test")
        self.assertIsNotNone(loaded)

        self.assertEqual(loaded.company_name, original.company_name)
        self.assertEqual(loaded.domain, original.domain)
        self.assertEqual(loaded.website, original.website)
        self.assertEqual(loaded.industry, original.industry)
        self.assertEqual(loaded.emails, original.emails)
        self.assertEqual(loaded.phones, original.phones)
        self.assertEqual(loaded.tech_stack, original.tech_stack)
        self.assertEqual(len(loaded.people), 2)
        self.assertEqual(loaded.people[0].name, "Dr. Jane Doe")
        self.assertEqual(loaded.people[0].role, "CTO")
        self.assertEqual(loaded.lead_score, 97)
        self.assertEqual(loaded.confidence_score, 94.0)

    # ── Test 5: Enrichment Preservation ───────────────────────────────────
    def test_enrichment_preservation(self):
        lead = LeadRecord(
            company_name="Enriched Logic Inc",
            domain="enrichedlogic.test",
            lead_score=93,
            domain_intel={
                "has_mx": True,
                "domain_age_years": 8,
                "tls_valid": True,
            },
            org_graph={
                "nodes": [{"name": "Enriched Logic", "type": "company"}],
                "edges": [{"source": "Enriched Logic", "target": "CEO", "relation": "employs"}],
            },
        )
        self.repo.upsert_lead(lead)
        fetched = self.repo.get_lead_by_domain("enrichedlogic.test")

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.lead_score, 93)
        self.assertIsInstance(fetched.domain_intel, dict)
        self.assertTrue(fetched.domain_intel.get("has_mx"))
        self.assertEqual(fetched.domain_intel.get("domain_age_years"), 8)
        self.assertIsInstance(fetched.org_graph, dict)
        self.assertEqual(len(fetched.org_graph.get("nodes", [])), 1)

    # ── Test 6: Bulk Upsert & Count ───────────────────────────────────────
    def test_bulk_upsert_and_count(self):
        items = [
            LeadRecord(company_name=f"Bulk Co {i}", domain=f"bulk{i}.test", lead_score=50 + i)
            for i in range(10)
        ]
        inserted = self.repo.bulk_upsert_leads(items)
        self.assertEqual(inserted, 10)
        self.assertEqual(self.repo.count_leads(), 10)

        # Upserting duplicate domain updates without increasing count
        duplicate = LeadRecord(company_name="Bulk Co 0 Updated", domain="bulk0.test", lead_score=99)
        self.repo.upsert_lead(duplicate)
        self.assertEqual(self.repo.count_leads(), 10)
        updated = self.repo.get_lead_by_domain("bulk0.test")
        self.assertEqual(updated.company_name, "Bulk Co 0 Updated")
        self.assertEqual(updated.lead_score, 99)

    # ── Test 7: API Read from Canonical Storage ───────────────────────────
    def test_api_reads_from_canonical_storage(self):
        import api
        orig_db = api.DB_PATH
        api.DB_PATH = self.db_path

        try:
            # Seed canonical flowiz_leads via repo
            self.repo.upsert_lead(LeadRecord(
                company_name="Canonical API Test Co",
                domain="canonical-api.test",
                industry="AI",
                lead_score=91,
                domain_intel={"checked": True},
                org_graph={"size": "medium"},
                keyword="canonical test",
            ))

            # Query root API
            resp = api.get_leads(domain="canonical-api.test")
            leads = resp.get("leads", [])
            self.assertEqual(len(leads), 1)
            first = leads[0]
            self.assertEqual(first["company_name"], "Canonical API Test Co")
            self.assertEqual(first["domain"], "canonical-api.test")
            self.assertEqual(first["lead_score"], 91)
            self.assertEqual(first["domain_intel"], {"checked": True})
            self.assertEqual(first["org_graph"], {"size": "medium"})

            # Query bulk all leads endpoint
            bulk_resp = api.get_all_leads()
            self.assertEqual(bulk_resp["status"], "success")
            self.assertEqual(bulk_resp["count"], 1)
        finally:
            api.DB_PATH = orig_db

    # ── Test 8: Pillar 4 API Compatibility ────────────────────────────────
    def test_pillar_4_api_reads_from_canonical_storage(self):
        from pillar_4_pipeline import api as p4_api
        orig_db = p4_api.DB_FILE
        p4_api.DB_FILE = self.db_path

        try:
            self.repo.upsert_lead(LeadRecord(
                company_name="Pillar 4 Sync Co",
                domain="p4sync.test",
                industry="Fintech",
                lead_score=85,
            ))

            bulk = p4_api.get_all_leads()
            self.assertEqual(bulk["status"], "success")
            self.assertGreaterEqual(bulk["count"], 1)

            filtered = p4_api.get_leads(domain="p4sync.test")
            self.assertEqual(filtered["status"], "success")
            self.assertEqual(filtered["data"][0]["company_name"], "Pillar 4 Sync Co")
        finally:
            p4_api.DB_FILE = orig_db

    # ── Test 9: Legacy Migration Safety & Idempotency ──────────────────────
    def test_legacy_migration_safety(self):
        # Create legacy table manually and insert 2 legacy leads
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT,
                website TEXT,
                industry TEXT,
                keyword TEXT
            )
        """)
        conn.execute("INSERT INTO leads (company_name, website, industry, keyword) VALUES ('Legacy 1', 'https://legacy1.test', 'AI', 'legacy')")
        conn.execute("INSERT INTO leads (company_name, website, industry, keyword) VALUES ('Legacy 2', 'https://legacy2.test', 'SaaS', 'legacy')")
        conn.commit()
        conn.close()

        # Run migration
        result = self.repo.migrate_from_legacy_leads()
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["migrated"], 2)

        # Verify migrated records exist in canonical flowiz_leads
        lead1 = self.repo.get_lead_by_domain("legacy1.test")
        self.assertIsNotNone(lead1)
        self.assertEqual(lead1.company_name, "Legacy 1")
        self.assertEqual(lead1.industry, "AI")

        # Run migration second time: must be idempotent (0 newly migrated)
        result2 = self.repo.migrate_from_legacy_leads()
        self.assertEqual(result2["migrated"], 0)
        self.assertEqual(result2["already_existed"], 2)

    # ── Test 10: Database Path Consistency ────────────────────────────────
    def test_database_path_consistency(self):
        default_path = get_default_db_path()
        self.assertTrue(default_path.endswith("leads.db"))
        repo_default = LeadRepository()
        self.assertEqual(repo_default.db_path, default_path)


if __name__ == "__main__":
    unittest.main()
