import os
import sys
import pytest

# Ensure project root is in sys.path
proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)
pillar1_path = os.path.join(proj_root, "pillar1")
if pillar1_path not in sys.path:
    sys.path.insert(0, pillar1_path)

from pillar1.browser.browser_manager import get_browser_manager
from pillar1.browser.cookie_manager import CookieManager

def test_cookie_manager_validation(tmp_path):
    # Test cookie management and expiration checks
    cm = CookieManager(base_dir=str(tmp_path / "cookies"))
    test_cookies = [
        {"name": "session_id", "value": "xyz123", "domain": ".google.com", "path": "/"},
        {"name": "expired_token", "value": "abc", "domain": ".google.com", "path": "/", "expires": 1000.0}, # Very old
        {"name": "valid_token", "value": "def", "domain": ".google.com", "path": "/", "expires": 9999999999.0} # Future
    ]
    cm.save_cookies("google.com", test_cookies)
    
    loaded = cm.load_cookies("google.com")
    assert len(loaded) == 2
    names = [c["name"] for c in loaded]
    assert "session_id" in names
    assert "valid_token" in names
    assert "expired_token" not in names

def test_browser_manager_and_pool():
    from unittest.mock import patch
    with patch("pillar1.browser.browser_instance.BrowserInstance.warm_up", return_value=True):
        bm = get_browser_manager()
        try:
            # Initialize pool dynamically
            bm.initialize()
            assert bm._initialized is True
            assert bm.pool is not None
            assert bm.pool.pool_size >= 1
            
            # Test browser retrieval
            instance = bm.get_browser()
            assert instance is not None
            assert instance.browser is not None
            assert instance.requests_count == 0
            
            # Test scoring scheduler
            score = bm.pool.calculate_score(instance)
            assert score > 0.0
            
            # Verify memory usage retrieval is safe
            mem = instance.get_memory_usage()
            assert mem >= 0.0
            
        finally:
            bm.shutdown()
            assert bm._initialized is False
            assert bm.pool is None

def test_browser_circuit_breaker():
    from pillar1.browser.browser_breaker import BrowserCircuitBreaker
    breaker = BrowserCircuitBreaker(failure_threshold=3, cooldown_duration=1.0)
    
    assert breaker.is_blocked("test_provider") is False
    
    breaker.record_failure("test_provider")
    breaker.record_failure("test_provider")
    assert breaker.is_blocked("test_provider") is False
    
    breaker.record_failure("test_provider")
    assert breaker.is_blocked("test_provider") is True
    
    breaker.record_success("test_provider")
    assert breaker.is_blocked("test_provider") is False

def test_proxy_only_enforcement():
    from unittest.mock import MagicMock, patch
    bm = get_browser_manager()
    bm.initialize()
    try:
        # Mock ProxyManager returning None (no proxies)
        mock_pm = MagicMock()
        mock_pm.get_proxy.return_value = None
        
        with patch("pillar1.browser.browser_pool.get_proxy_manager", return_value=mock_pm):
            # Since playwright_google is proxy_only, creating it with no proxies should return None
            inst = bm.pool._create_new_instance(99, "playwright_google")
            assert inst is None
            
            # Since brave is direct_first, creating it with no proxies should proceed (using direct connection)
            # (We will mock the launch to return a mock instance to avoid starting actual browser here)
            with patch("pillar1.browser.browser_instance.BrowserInstance.launch", return_value=True):
                with patch("pillar1.browser.browser_instance.BrowserInstance.warm_up", return_value=True):
                    inst_direct = bm.pool._create_new_instance(99, "brave")
                    assert inst_direct is not None
                    assert inst_direct.proxy_url is None
    finally:
        bm.shutdown()

def test_isolated_memory_tracking():
    from unittest.mock import patch, MagicMock
    from pillar1.browser.browser_instance import BrowserInstance
    
    # Create an instance
    inst = BrowserInstance(playwright_instance=MagicMock(), proxy_url=None, index=1)
    
    # Mock psutil.process_iter to return a process containing the unique flag in cmdline
    unique_flag = f"--playwright-browser-id={id(inst)}"
    
    mock_proc = MagicMock()
    mock_proc.info = {
        'cmdline': ['chrome.exe', '--some-flag', unique_flag],
        'pid': 12345,
        'name': 'chrome.exe'
    }
    mock_proc.memory_info.return_value.rss = 50 * 1024 * 1024 # 50 MB
    
    # Mock child process
    mock_child = MagicMock()
    mock_child.memory_info.return_value.rss = 30 * 1024 * 1024 # 30 MB
    mock_proc.children.return_value = [mock_child]
    
    with patch("psutil.process_iter", return_value=[mock_proc]):
        mem = inst.get_memory_usage()
        # RSS should sum to 80 MB (50 + 30)
        assert mem == 80.0

