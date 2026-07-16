from network_client_project.network.proxy_manager import Proxy


def test_proxy_tracks_provider_capabilities():
    proxy = Proxy(raw_url="http://proxy.example:8080")

    proxy.record_failure(domain="google", reason="CAPTCHA")
    assert proxy.get_provider_capability("google") == "blocked"

    proxy.record_success(domain="bing", reason="VALID_RESULTS")
    assert proxy.get_provider_capability("bing") == "good"

    proxy.record_success(domain="duckduckgo", reason="VALID_RESULTS")
    assert proxy.get_provider_capability("duckduckgo") == "good"
