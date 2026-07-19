import time
import pytest
from unittest.mock import MagicMock, patch
from extraction.page_extractor import fetch_page, _domain_cooldowns, _domain_consecutive_blocks
from network_client_project.network.proxy_manager import Proxy

def test_domain_circuit_breaker():
    # Clear circuit breaker state
    _domain_consecutive_blocks.clear()
    _domain_cooldowns.clear()
    
    # Mock NetworkClient to always fail with a non-HTML or block status
    with patch("network_client_project.network.NetworkClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.text = "WAF Block"
        mock_client.get.return_value = mock_resp
        
        # Run fetch_page 10 times to trip the circuit breaker
        url = "https://www.testblockeddomain.com/some-page"
        for _ in range(10):
            fetch_page(url)
            
        # Verify domain is now in cooldown
        domain_key = "testblockeddomain.com"
        assert domain_key in _domain_cooldowns
        assert _domain_cooldowns[domain_key] > time.time()
        
        # Verify next call returns None immediately without calling client.get
        mock_client.get.reset_mock()
        res = fetch_page(url)
        assert res is None
        mock_client.get.assert_not_called()

def test_custom_google_cooldowns():
    # Verify that a Google failure sets a strict long cooldown of 15 or 30 minutes
    p = Proxy(raw_url="http://12.34.56.78:8080")
    
    # 429 block -> 15 min cooldown (900 seconds)
    p.record_failure(domain="www.google.com", reason="RATE_LIMIT")
    assert p.cooldown_until["www.google.com"] >= time.time() + 890.0
    
    # CAPTCHA block -> 30 min cooldown (1800 seconds)
    p.record_failure(domain="www.google.com", reason="CAPTCHA")
    assert p.cooldown_until["www.google.com"] >= time.time() + 1790.0

def test_url_filtering():
    from search.manager import is_valid_company_url
    # Valid company URLs
    assert is_valid_company_url("https://www.example.com") is True
    assert is_valid_company_url("http://example.org/about") is True
    assert is_valid_company_url("https://subdomain.company.co.uk") is True
    
    # Invalid/garbage/internal search engine URLs
    assert is_valid_company_url("/search?q=python") is False
    assert is_valid_company_url("https:///search?q=python") is False
    assert is_valid_company_url("https://www.google.com/search?q=python") is False
    assert is_valid_company_url("https://www.google.com.vn/intl/en/about") is False
    assert is_valid_company_url("https://google.com/search") is False
    assert is_valid_company_url("invalid_url") is False
    assert is_valid_company_url("http://google.com") is False
    assert is_valid_company_url("https://site.com/search?q=somequery") is False
    assert is_valid_company_url("https://site.com/search") is False
    assert is_valid_company_url("https://site com/page") is False
    assert is_valid_company_url("https://site!com") is False

