"""
tests/test_pipeline_to_api_contract.py
========================================
Phase 1 Step 6 — End-to-end pipeline -> DB -> API contract test.

Verifies that a lead card produced by build_lead_card() survives the full
chain and is retrievable via get_leads() with all required fields present
and correctly typed.

What this catches that unit tests don't
---------------------------------------
- _save_leads_to_db() silently drops a field (schema gap in INSERT).
- get_leads() returns raw JSON strings instead of parsed lists for
  emails / tech_stack / people.
- A field in the card dict is not in the INSERT statement (write-time loss).
- A field in the DB is not returned by SELECT * (read-time loss).
- JSON arrays are stored but not deserialized back to list on read.

This test must pass before Phase 2 work begins.
"""

import json
import os
import sqlite3
import tempfile
import unittest

# ── Required fields and their accepted types ──────────────────────────────────
# These map exactly to what the frontend needs from GET /api/leads.
REQUIRED_FIELDS: dict[str, type | tuple] = {
    "company_name":     str,
    "website":          (str, type(None)),
    "linkedin":         (str, type(None)),
    "industry":         (str, type(None)),
    "location":         (str, type(None)),
    "emails":           list,
    "email_candidates": list,
    "phones":           list,
    "tech_stack":       list,
    "people":           list,
    "confidence_score": (int, float),
    "lead_quality":     str,
    "keyword":          str,
}

# Fields that must contain actual data (non-empty), not just be present
NON_EMPTY_FIELDS = ["company_name", "emails", "tech_stack", "people"]


def _make_complete_lead_card() -> dict:
    """
    Minimal but complete lead card matching what build_lead_card() returns.
    """
    return {
        "company_name":     "Acme Corp",
        "website":          "https://acme.io",
        "linkedin":         "https://linkedin.com/company/acme",
        "industry":         "SaaS",
        "location":         "Chicago, IL",
        "contact_page":     "https://acme.io/contact",
        "about_page":       "https://acme.io/about",
        "team_page":        "https://acme.io/team",
        "emails":           ["hello@acme.io", "sales@acme.io"],
        "email_candidates": [{"email": "info@acme.io", "source": "generated_pattern", "verified": False}],
        "phones":           ["+1 312-555-0101"],
        "social_links":     {"linkedin": "https://linkedin.com/company/acme",
                             "twitter": "https://twitter.com/acme"},
        "people":           [{"name": "Jane Doe", "designation": "CEO",
                              "decision_maker_score": 100},
                             {"name": "John Smith", "designation": "CTO",
                              "decision_maker_score": 85}],
        "source":           "google",
        "confidence_score": 85,
        "lead_quality":     "High",
        "company_type":     "B2B SaaS",
        "tech_stack":       ["React", "AWS", "Stripe"],
        "description":      "Acme builds cloud widgets for enterprise teams.",
        "employees":        "50-200",
        "founded":          "2018",
        "country":          "US",
        "relevance_score":  85,
        "relevance_tier":   "HIGH",
        "relevance_info":   {"matched_signals": ["SaaS", "B2B"]},
    }


class TestPipelineToApiContract(unittest.TestCase):
    """
    Contract test: a complete lead card must survive
      build_lead_card() dict  ->  _save_leads_to_db()  ->  get_leads()
    with all required fields present and correctly typed.
    """

    def setUp(self):
        # Isolated temp directory — isolates both the DB and the JSON-fallback
        # path (api.ROOT / output / final) from production files.
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.tmp_db = os.path.join(self._tmpdir, "leads_test.db")

        import api as api_mod
        self._api = api_mod
        self._orig_db   = api_mod.DB_PATH
        self._orig_root = api_mod.ROOT

        # Point both DB and ROOT at temp dir so the JSON fallback finds nothing
        api_mod.DB_PATH = self.tmp_db
        api_mod.ROOT    = self._tmpdir

        # Cold-start table creation
        api_mod.init_db()

    def tearDown(self):
        self._api.DB_PATH = self._orig_db
        self._api.ROOT    = self._orig_root
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _save_and_fetch(self, card: dict, keyword: str = "saas chicago") -> dict:
        """Save one card, fetch all leads, return the first (and only) lead."""
        self._api._save_leads_to_db([card], keyword=keyword)
        resp = self._api.get_leads()
        leads = resp.get("leads", [])
        self.assertEqual(len(leads), 1,
            f"Expected exactly 1 lead after saving, got {len(leads)}")
        return leads[0]

    # ── contract tests ────────────────────────────────────────────────────────

    def test_all_required_fields_present(self):
        """Every field in REQUIRED_FIELDS must exist in the API response."""
        lead = self._save_and_fetch(_make_complete_lead_card())
        for field in REQUIRED_FIELDS:
            self.assertIn(field, lead,
                f"Required field '{field}' is missing from API response.\n"
                f"Returned keys: {sorted(lead.keys())}")

    def test_required_field_types(self):
        """Every required field must have the expected Python type."""
        lead = self._save_and_fetch(_make_complete_lead_card())
        for field, expected_type in REQUIRED_FIELDS.items():
            self.assertIsInstance(lead.get(field), expected_type,
                f"Field '{field}': expected {expected_type}, "
                f"got {type(lead.get(field))} (value={lead.get(field)!r})")

    def test_json_array_fields_are_deserialized(self):
        """
        emails, phones, tech_stack, people must be Python lists in the API
        response — not raw JSON strings.
        """
        lead = self._save_and_fetch(_make_complete_lead_card())
        for field in ("emails", "phones", "tech_stack", "people"):
            val = lead.get(field)
            self.assertIsInstance(val, list,
                f"Field '{field}' must be a list after deserialization, "
                f"got {type(val)}: {val!r}")

    def test_non_empty_fields_have_data(self):
        """Fields that must not be empty actually contain data."""
        lead = self._save_and_fetch(_make_complete_lead_card())
        for field in NON_EMPTY_FIELDS:
            val = lead.get(field)
            if isinstance(val, list):
                self.assertGreater(len(val), 0,
                    f"Field '{field}' is an empty list — data lost in pipeline")
            else:
                self.assertTrue(val,
                    f"Field '{field}' is falsy — data lost in pipeline")

    def test_emails_content_preserved(self):
        """Exact email values must survive the round-trip."""
        card = _make_complete_lead_card()
        lead = self._save_and_fetch(card)
        self.assertEqual(sorted(lead["emails"]), sorted(card["emails"]),
            "Email content changed between save and fetch")

    def test_tech_stack_content_preserved(self):
        """Tech stack items must survive the round-trip."""
        card = _make_complete_lead_card()
        lead = self._save_and_fetch(card)
        self.assertEqual(sorted(lead["tech_stack"]), sorted(card["tech_stack"]),
            "tech_stack content changed between save and fetch")

    def test_people_content_preserved(self):
        """People list (with name + designation) must survive."""
        card = _make_complete_lead_card()
        lead = self._save_and_fetch(card)
        names_in = sorted(p["name"] for p in card["people"])
        names_out = sorted(p["name"] for p in lead["people"])
        self.assertEqual(names_in, names_out,
            "people names changed between save and fetch")

    def test_keyword_is_stored(self):
        """keyword passed to _save_leads_to_db must appear in the lead."""
        lead = self._save_and_fetch(_make_complete_lead_card(), keyword="fintech london")
        self.assertEqual(lead["keyword"].lower(), "fintech london",
            "keyword not stored or returned correctly")

    def test_confidence_score_is_numeric(self):
        """confidence_score must be numeric (int or float), not a string."""
        card = _make_complete_lead_card()
        card["confidence_score"] = 92.5
        lead = self._save_and_fetch(card)
        self.assertIsInstance(lead["confidence_score"], (int, float),
            f"confidence_score must be numeric, got {type(lead['confidence_score'])}")
        self.assertAlmostEqual(lead["confidence_score"], 92.5, places=1)

    def test_null_optional_fields_dont_break_response(self):
        """A card with None for optional fields must still be saved and returned."""
        card = _make_complete_lead_card()
        card["linkedin"] = None
        card["location"] = None
        card["founded"] = None
        card["country"] = None
        card["description"] = None
        lead = self._save_and_fetch(card)
        # Required non-nullable fields still present
        self.assertIn("company_name", lead)
        self.assertIsInstance(lead["emails"], list)

    def test_count_field_in_response(self):
        """get_leads() response must include a 'count' key matching len(leads)."""
        self._api._save_leads_to_db([_make_complete_lead_card()], keyword="test")
        resp = self._api.get_leads()
        self.assertIn("count", resp)
        self.assertEqual(resp["count"], len(resp.get("leads", [])))

    def test_cold_start_get_leads_returns_empty_not_error(self):
        """
        GET /api/leads on a brand-new DB (no pipeline run yet) must return
        an empty list, not raise 'no such table: leads'.
        """
        resp = self._api.get_leads()
        self.assertIn("leads", resp, "Response must always have 'leads' key")
        self.assertIsInstance(resp["leads"], list)
        # No rows yet — but no crash either
        self.assertEqual(resp["count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
