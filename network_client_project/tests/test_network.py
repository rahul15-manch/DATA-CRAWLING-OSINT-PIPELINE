import pytest
import time
from unittest.mock import patch, MagicMock

from network.config import config
from network.proxy_manager import ProxyManager
from network.user_agents import UserAgentManager
from network.headers import HeaderManager
from network.client import NetworkClient

def test_proxy_rotation_on_failure():
    """Test that a sticky session rotates to a new proxy if the current one fails."""
    manager = ProxyManager()
    manager.load_from_list(["1.1.1.1", "2.2.2.2"])
    
    session_id = "test_session"
    proxy1 = manager.get_proxy(session_id)
    assert proxy1 is not None
    
    # Simulate failure and cooldown
    proxy1.record_failure(cooldown_seconds=60)
    
    # Request proxy again for the same session ID
    proxy2 = manager.get_proxy(session_id)
    assert proxy2 is not None
    assert proxy1 is not proxy2 # Should be a different proxy
    assert proxy2.raw_url != proxy1.raw_url

def test_user_agent_rotation():
    """Test that consecutive calls to UserAgentManager do not return the same UA if possible."""
    ua_manager = UserAgentManager()
    
    # fake_useragent with min_percentage=1.3 sometimes yields only 1 element, breaking rotation tests.
    # Force the use of fallbacks which are guaranteed to have multiple elements.
    ua_manager.ua_generator = None
    
    # Test get_random (Relaxed assertion due to fake_useragent flakiness)
    rotated = False
    ua1 = ua_manager.get_random()
    for _ in range(10):
        ua2 = ua_manager.get_random()
        if ua1 != ua2:
            rotated = True
            break
    assert rotated, "UA failed to rotate after 10 attempts"
    
    # Test get_chrome_desktop
    rotated_chrome = False
    ua3 = ua_manager.get_chrome_desktop()
    for _ in range(10):
        ua4 = ua_manager.get_chrome_desktop()
        if ua3 != ua4:
            rotated_chrome = True
            break
    assert rotated_chrome, "Chrome UA failed to rotate after 10 attempts"

def test_ssl_verification_config():
    """Test that the VERIFY_SSL config is correctly applied."""
    client = NetworkClient()
    
    # By default, verify should be whatever is in config (True)
    req_params = client._prepare_request("GET", "https://example.com", "test_ssl")
    assert req_params["verify"] == config.VERIFY_SSL
    
    # Change config and test again
    original_verify = config.VERIFY_SSL
    config.VERIFY_SSL = not original_verify
    req_params2 = client._prepare_request("GET", "https://example.com", "test_ssl_2")
    assert req_params2["verify"] == config.VERIFY_SSL
    
    # Restore config
    config.VERIFY_SSL = original_verify

def test_browser_header_generation():
    """Test that header manager correctly generates realistic headers."""
    hm = HeaderManager()
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    headers = hm.generate_browser_headers("https://example.com", ua)
    
    assert headers["User-Agent"] == ua
    assert "sec-ch-ua" in headers
    assert "sec-ch-ua-mobile" in headers
    assert "sec-ch-ua-platform" in headers

@patch('network.session_manager.requests.Session')
def test_retry_after_proxy_failure(mock_session_class):
    """Test that the NetworkClient retries and requests a fresh proxy on network failure."""
    client = NetworkClient()
    client.proxy_manager.load_from_list(["1.1.1.1", "2.2.2.2"])
    
    # Mock the session to fail on the first try, succeed on the second
    mock_session = MagicMock()
    mock_session_class.return_value = mock_session
    
    # Setup mock request to raise RequestException once, then return success
    from curl_cffi.requests.exceptions import RequestException
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    mock_session.request.side_effect = [RequestException("Network Error"), mock_response]
    
    # Mock get_or_create_session to return our mock
    client.session_manager.get_or_create_session = MagicMock(return_value=mock_session)
    
    # Mock error detector so it doesn't trigger WAF
    from network.exceptions import ErrorDetector
    with patch.object(ErrorDetector, 'detect_waf_or_captcha', return_value=None):
        response = client.get("https://example.com", session_id="test_retry")
        assert response.status_code == 200
        assert mock_session.request.call_count == 2
