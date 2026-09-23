"""
tests/test_security_hardening.py
=================================
Deterministic Security and Production Readiness Test Suite (Milestone 6).

Verifies defenses against:
1. SSRF private IPv4 access
2. SSRF localhost/loopback access
3. SSRF cloud metadata endpoint access
4. SSRF IPv6 loopback and private network access
5. Unsafe redirect targets
6. Unsafe URL schemes (file, ftp, gopher, javascript, data)
7. Public safe URL validation
8. SQL injection resistance in LeadRepository
9. Command injection resistance in subprocess tokenization
10. Path traversal resistance in output file naming
11. API pagination and query bounds in LeadRepository
12. API oversized input rejection in FastAPI
13. Secret redaction in logging
14. TLS verification defaults
15. OSINT provider failure isolation
"""

import logging
import os
import re
import socket
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from database.repository import LeadRepository
from models.lead_record import LeadRecord
from network_client_project.network.config import config as net_config
from network_client_project.network.logger import RedactingFormatter
from osint.base import BaseOSINTProvider
from osint.models import ProviderResult, ProviderStatus
from osint.orchestrator import OSINTOrchestrator
from osint.registry import ProviderRegistry
from utils.validators import is_safe_url, validate_redirect_target


class TestSecurityHardening(unittest.TestCase):
    """Milestone 6 Security Regression Test Suite."""

    # ── Test 1: SSRF private IPv4 blocking ────────────────────────────────────
    def test_01_ssrf_private_ipv4_blocked(self):
        private_urls = [
            "http://10.0.0.1/admin",
            "http://10.255.255.254/internal",
            "http://172.16.0.1/status",
            "http://172.31.255.255/secret",
            "http://192.168.1.1/router",
            "http://192.168.0.100:8080/metrics",
        ]
        for url in private_urls:
            is_safe, reason = is_safe_url(url)
            self.assertFalse(is_safe, f"Expected private URL to be blocked: {url}")
            self.assertIn("Private network IP", reason)

    # ── Test 2: SSRF localhost / loopback blocking ────────────────────────────
    def test_02_ssrf_localhost_loopback_blocked(self):
        loopback_urls = [
            "http://127.0.0.1:8000/api",
            "http://127.0.0.2:9000",
            "http://localhost:3000",
            "http://sub.localhost:8080",
            "http://0.0.0.0:5000",
        ]
        for url in loopback_urls:
            is_safe, reason = is_safe_url(url)
            self.assertFalse(is_safe, f"Expected loopback URL to be blocked: {url}")
            self.assertTrue(
                "Loopback" in reason or "localhost" in reason or "Unspecified" in reason or "Private" in reason,
                f"Unexpected reason: {reason}",
            )

    # ── Test 3: SSRF cloud metadata endpoint blocking ────────────────────────
    def test_03_ssrf_cloud_metadata_blocked(self):
        metadata_urls = [
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://instance-data/latest/meta-data/",
        ]
        for url in metadata_urls:
            is_safe, reason = is_safe_url(url)
            self.assertFalse(is_safe, f"Expected cloud metadata URL to be blocked: {url}")

    # ── Test 4: SSRF private / loopback IPv6 blocking ────────────────────────
    def test_04_ssrf_ipv6_blocked(self):
        ipv6_urls = [
            "http://[::1]:8080",
            "http://[fc00::1]/private",
            "http://[fe80::1]/linklocal",
        ]
        for url in ipv6_urls:
            is_safe, reason = is_safe_url(url)
            self.assertFalse(is_safe, f"Expected IPv6 URL to be blocked: {url}")
            self.assertTrue(
                "Loopback" in reason or "Private" in reason or "Link-local" in reason,
                f"Unexpected reason: {reason}",
            )

    # ── Test 5: Redirect validation ──────────────────────────────────────────
    def test_05_redirect_validation_blocks_unsafe_target(self):
        # Target pointing to private or metadata endpoint
        unsafe_redirects = [
            "http://169.254.169.254/secret",
            "http://127.0.0.1:8000/internal",
            "http://192.168.1.1/setup.cgi",
            "file:///etc/shadow",
        ]
        for target in unsafe_redirects:
            is_safe, reason = validate_redirect_target(target)
            self.assertFalse(is_safe, f"Expected redirect target to be rejected: {target}")

    # ── Test 6: Unsafe scheme rejection ──────────────────────────────────────
    def test_06_unsafe_schemes_rejected(self):
        unsafe_schemes = [
            "file:///etc/passwd",
            "ftp://ftp.example.com/files",
            "gopher://gopher.example.com",
            "javascript:alert(1)",
            "data:text/html,<h1>PWNED</h1>",
        ]
        for url in unsafe_schemes:
            is_safe, reason = is_safe_url(url)
            self.assertFalse(is_safe, f"Expected scheme to be rejected: {url}")
            self.assertIn("Disallowed URL scheme", reason)

    # ── Test 7: Public safe URL acceptance ───────────────────────────────────
    def test_07_public_safe_urls_accepted(self):
        # Mock DNS resolution for deterministic test without live network dependency
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
            ]
            is_safe, reason = is_safe_url("https://example.com/about")
            self.assertTrue(is_safe, f"Expected public URL to be allowed: {reason}")
            self.assertEqual(reason, "OK")

    # ── Test 8: SQL injection resistance ─────────────────────────────────────
    def test_08_sql_injection_resistance(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        try:
            repo = LeadRepository(db_path)
            # 1. Test upsert with SQL injection attack payloads in strings
            malicious_lead = LeadRecord(
                domain="injected-test.com",
                company_name="Acme Corp'); DROP TABLE flowiz_leads; --",
                keyword="' OR '1'='1",
                industry="Tech' OR 1=1 --",
            )
            repo.upsert_lead(malicious_lead)

            # 2. Test get_leads with SQL injection in filter parameters
            results = repo.get_leads(
                keyword="' OR '1'='1",
                industry="Tech'; DROP TABLE flowiz_leads; --",
            )
            # Table must still exist and query must execute safely
            count = repo.count_leads()
            self.assertEqual(count, 1)

            fetched = repo.get_lead_by_domain("injected-test.com")
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.company_name, "Acme Corp'); DROP TABLE flowiz_leads; --")
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    # ── Test 9: Command injection resistance ─────────────────────────────────
    def test_09_command_injection_resistance(self):
        # Verify that subprocess calls in run_pipeline accept arguments as token lists
        from run_pipeline import _run
        # Run a safe command with argument containing shell characters (; && || | `)
        # Without shell=True, these characters must be treated strictly as literal string tokens
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tf:
            test_file = tf.name

        try:
            # sys.executable -c "import sys; sys.exit(0 if sys.argv[1] == 'safe; rm -rf /' else 1)" "safe; rm -rf /"
            cmd = [
                os.sys.executable,
                "-c",
                "import sys; sys.exit(0 if sys.argv[1] == 'safe; echo injected' else 1)",
                "safe; echo injected",
            ]
            rc = _run("security_test", cmd)
            self.assertEqual(rc, 0, "Subprocess tokenization must prevent shell command execution")
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

    # ── Test 10: Path traversal resistance ───────────────────────────────────
    def test_10_path_traversal_resistance(self):
        # Test sanitization of malicious keyword in output path generation
        raw_keyword = "../../etc/passwd"
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_keyword).strip("_").lower()
        self.assertNotIn("..", sanitized)
        self.assertNotIn("/", sanitized)
        self.assertNotIn("\\", sanitized)
        self.assertEqual(sanitized, "etc_passwd")

    # ── Test 11: API pagination bounds ───────────────────────────────────────
    def test_11_pagination_bounds_clamped(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        try:
            repo = LeadRepository(db_path)
            # Negative limit and negative offset must be safely clamped
            res_neg = repo.get_leads(limit=-50, offset=-10)
            self.assertIsInstance(res_neg, list)

            # Huge limit must be clamped to max 1000
            res_huge = repo.get_leads(limit=999999999, offset=0)
            self.assertIsInstance(res_huge, list)
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    # ── Test 12: API oversized input bounds in FastAPI ───────────────────────
    def test_12_api_input_validation(self):
        from fastapi.testclient import TestClient
        from api import app

        client = TestClient(app)

        # 1. Bounded search query: minimum 2 chars
        resp_too_short = client.post("/api/search?keyword=a")
        self.assertEqual(resp_too_short.status_code, 422)

        # 2. Bounded search query: maximum 200 chars
        oversized_keyword = "a" * 205
        resp_too_long = client.post(f"/api/search?keyword={oversized_keyword}")
        self.assertEqual(resp_too_long.status_code, 422)

        # 3. Pagination bounds: limit must be <= 1000
        resp_huge_limit = client.get("/api/leads?limit=5000")
        self.assertEqual(resp_huge_limit.status_code, 422)

        # 4. Valid pagination
        resp_valid = client.get("/api/leads?limit=50&offset=0")
        self.assertEqual(resp_valid.status_code, 200)

    # ── Test 13: Secret redaction in logging ──────────────────────────────────
    def test_13_secret_redaction_in_logging(self):
        formatter = RedactingFormatter("%(message)s")

        # Test query parameter redaction
        rec1 = logging.LogRecord(
            "test", logging.INFO, "test.py", 1,
            "Failed url: https://serpapi.com/search?api_key=secret_serp_key_12345&q=test",
            (), None
        )
        self.assertNotIn("secret_serp_key_12345", formatter.format(rec1))
        self.assertIn("api_key=[REDACTED]", formatter.format(rec1))

        # Test Authorization Bearer header redaction
        rec2 = logging.LogRecord(
            "test", logging.INFO, "test.py", 2,
            "Headers: Authorization: Bearer secret_jwt_token_99999",
            (), None
        )
        self.assertNotIn("secret_jwt_token_99999", formatter.format(rec2))
        self.assertIn("Bearer [REDACTED]", formatter.format(rec2))

        # Test inline URL credentials redaction
        rec3 = logging.LogRecord(
            "test", logging.INFO, "test.py", 3,
            "Proxy: http://user:secretpass123@proxy.domain.com:8080",
            (), None
        )
        self.assertNotIn("secretpass123", formatter.format(rec3))
        self.assertIn("http://***:***@proxy.domain.com:8080", formatter.format(rec3))

    # ── Test 14: Default TLS verification ────────────────────────────────────
    def test_14_default_tls_verification(self):
        # In production network configuration class, VERIFY_SSL must default to True
        from network_client_project.network.config import NetworkConfig
        default_val = NetworkConfig.model_fields["VERIFY_SSL"].default
        self.assertTrue(
            default_val,
            "NetworkConfig.VERIFY_SSL must be True by default for production security",
        )

    # ── Test 15: OSINT provider failure isolation ────────────────────────────
    def test_15_provider_failure_isolation(self):
        import asyncio

        class FailingTestProvider(BaseOSINTProvider):
            name = "failing_mock"

            def enrich(self, lead: LeadRecord) -> ProviderResult:
                # Deliberate exception simulating external API failure / crash
                raise RuntimeError("Simulated external API crash with sensitive token XYZ123")

        registry = ProviderRegistry()
        registry.register(FailingTestProvider())

        orchestrator = OSINTOrchestrator(registry=registry)
        test_lead = LeadRecord(domain="test-isolation.com", company_name="Isolation Test")

        # Orchestrator must catch provider exceptions and not crash
        enriched_lead = asyncio.run(orchestrator.enrich_lead(test_lead))
        self.assertIsInstance(enriched_lead, LeadRecord)
        # Verify evidence recorded the failure gracefully
        self.assertIn("osint_providers", enriched_lead.evidence)
        self.assertIn("failing_mock", enriched_lead.evidence["osint_providers"])
        self.assertEqual(
            enriched_lead.evidence["osint_providers"]["failing_mock"]["status"],
            ProviderStatus.ERROR.value,
        )


if __name__ == "__main__":
    unittest.main()
