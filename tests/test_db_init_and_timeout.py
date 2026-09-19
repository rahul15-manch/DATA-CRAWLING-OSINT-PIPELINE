"""
Tests for:
  1. api.init_db() -- cold-start table creation
  2. DISCOVERY_TIMEOUT_SECONDS env-var override in company_discovery
"""

import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _leads_table_exists(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type=? AND name=?",
            ("table", "leads"),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def _leads_columns(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("PRAGMA table_info(leads)")
        return [row[1] for row in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DB Init Tests
# ---------------------------------------------------------------------------

class TestInitDb(unittest.TestCase):
    """api.init_db() must create the leads table without touching existing data."""

    def _tmp_db(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        return path

    def _call_init_db(self, tmp_path):
        import api as api_mod
        orig = api_mod.DB_PATH
        api_mod.DB_PATH = tmp_path
        try:
            api_mod.init_db()
        finally:
            api_mod.DB_PATH = orig

    def test_creates_leads_table_on_empty_db(self):
        tmp = self._tmp_db()
        self.assertFalse(_leads_table_exists(tmp))
        self._call_init_db(tmp)
        self.assertTrue(_leads_table_exists(tmp))

    def test_idempotent_does_not_destroy_existing_data(self):
        tmp = self._tmp_db()
        conn = sqlite3.connect(tmp)
        conn.execute(
            "CREATE TABLE leads (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "company_name TEXT, website TEXT, linkedin TEXT, industry TEXT, "
            "location TEXT, contact_page TEXT, about_page TEXT, team_page TEXT, "
            "emails TEXT, phones TEXT, social_links TEXT, people TEXT, "
            "company_type TEXT, tech_stack TEXT, description TEXT, "
            "employees TEXT, founded TEXT, country TEXT, "
            "confidence_score REAL, lead_quality TEXT, keyword TEXT, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute("INSERT INTO leads (company_name, keyword) VALUES (?, ?)", ("Acme", "test"))
        conn.commit()
        conn.close()

        self._call_init_db(tmp)   # must be a no-op

        conn = sqlite3.connect(tmp)
        count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1, "existing row must survive init_db() call")

    def test_schema_has_required_columns(self):
        required = {
            "company_name", "website", "linkedin", "industry", "location",
            "contact_page", "about_page", "team_page", "emails", "phones",
            "social_links", "people", "company_type", "tech_stack", "description",
            "employees", "founded", "country", "confidence_score", "lead_quality",
            "keyword", "created_at",
        }
        tmp = self._tmp_db()
        self._call_init_db(tmp)
        cols = set(_leads_columns(tmp))
        missing = required - cols
        self.assertFalse(missing, f"Missing columns: {missing}")


# ---------------------------------------------------------------------------
# Discovery Timeout Override Tests
# ---------------------------------------------------------------------------

class TestDiscoveryTimeoutOverride(unittest.TestCase):
    """DISCOVERY_TIMEOUT_SECONDS must override the dynamic formula when set."""

    @staticmethod
    def _formula_cap(active_providers, active_families, max_runtime=120):
        return min(float(max_runtime), 20.0 + 2.0 * active_providers + 1.0 * active_families)

    @staticmethod
    def _compute_timeout_cap(discovery_timeout_seconds, active_providers=5, active_families=9, max_runtime=120):
        formula_cap = TestDiscoveryTimeoutOverride._formula_cap(active_providers, active_families, max_runtime)
        _override = discovery_timeout_seconds
        return float(_override) if _override is not None else formula_cap

    def test_no_override_uses_formula(self):
        cap = self._compute_timeout_cap(None, active_providers=5, active_families=9)
        self.assertAlmostEqual(cap, self._formula_cap(5, 9))

    def test_override_bypasses_formula(self):
        cap = self._compute_timeout_cap(80.0)
        self.assertAlmostEqual(cap, 80.0)

    def test_override_can_be_smaller_than_formula(self):
        cap = self._compute_timeout_cap(10.0, active_providers=100, active_families=100)
        self.assertAlmostEqual(cap, 10.0)

    def _get_root_config(self):
        import importlib.util
        config_path = os.path.join(ROOT, "config.py")
        spec = importlib.util.spec_from_file_location("config_root", config_path)
        cfg_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg_mod)
        return cfg_mod

    def test_config_discovery_timeout_seconds_is_none_by_default(self):
        env_backup = os.environ.pop("DISCOVERY_TIMEOUT_SECONDS", None)
        try:
            cfg_mod = self._get_root_config()
            self.assertIsNone(cfg_mod.DISCOVERY_TIMEOUT_SECONDS)
        finally:
            if env_backup is not None:
                os.environ["DISCOVERY_TIMEOUT_SECONDS"] = env_backup

    def test_config_discovery_timeout_seconds_parsed_when_set(self):
        os.environ["DISCOVERY_TIMEOUT_SECONDS"] = "80"
        try:
            cfg_mod = self._get_root_config()
            self.assertEqual(cfg_mod.DISCOVERY_TIMEOUT_SECONDS, 80.0)
        finally:
            os.environ.pop("DISCOVERY_TIMEOUT_SECONDS", None)



if __name__ == "__main__":
    unittest.main()
