import pytest
import time
from network.proxy_manager import ProxyManager, Proxy

@pytest.fixture
def proxy_manager():
    """Pytest fixture to provide a clean ProxyManager for every test."""
    manager = ProxyManager()
    manager.load_from_list([
        "http://user:pass@1.1.1.1:8000",
        "http://user:pass@2.2.2.2:8000",
        "http://user:pass@3.3.3.3:8000"
    ])
    return manager

def test_proxy_loading(proxy_manager):
    """Test if proxies are loaded correctly into the pool."""
    stats = proxy_manager.get_stats()
    assert stats["total"] == 3
    assert stats["healthy"] == 3

def test_proxy_cooldown(proxy_manager):
    """Test if a failing proxy is properly removed from rotation."""
    proxy = proxy_manager.get_proxy()
    assert proxy is not None
    
    # Simulate a network failure
    proxy.record_failure(cooldown_seconds=1.0)
    
    # Verify it is in cooldown
    assert proxy.is_cooling_down is True
    
    # We started with 3, one is cooling down, so 2 should be healthy
    stats = proxy_manager.get_stats()
    assert stats["healthy"] == 2

def test_sticky_sessions(proxy_manager):
    """Test if the manager returns the EXACT SAME proxy for the same session ID."""
    session_id = "test_login_flow"
    
    # Request a proxy for our session
    proxy1 = proxy_manager.get_proxy(session_id)
    
    # Request a proxy for the SAME session again
    proxy2 = proxy_manager.get_proxy(session_id)
    
    # Assert they are the exact same memory object (same IP)
    assert proxy1 is proxy2

def test_proxy_permanent_removal(proxy_manager):
    """Test if a consistently failing proxy is permanently deleted."""
    proxy = proxy_manager.get_proxy()
    
    # Fail it 5 times
    for _ in range(5):
        proxy.record_failure(cooldown_seconds=0.1)
        
    assert proxy.failure_count == 5
    
    # Run the cleanup job
    proxy_manager.remove_bad_proxies(max_failures=5)
    
    # Total pool size should now be 2
    stats = proxy_manager.get_stats()
    assert stats["total"] == 2
