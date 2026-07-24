import sys
sys.path.append('.')
from pillar3_network_resilience.network.client import NetworkClient
from pillar3_network_resilience.network.middleware.base import Request

client = NetworkClient()
url = "https://www.goodfirms.co/artificial-intelligence/prompt-engineering"

direct_req = Request(
    url=url,
    method="GET",
    timeout=8.0,
    meta={"proxy_strategy": "direct", "bypass_proxy": True}
)

try:
    print("Testing direct request...")
    resp = client.send_request(direct_req)
    print(f"Status Code: {resp.status_code}")
    print(f"Headers: {resp.headers}")
    print(f"Body length: {len(resp.text) if resp.text else 0}")
    print(f"Body snippet: {resp.text[:200] if resp.text else ''}")
except Exception as e:
    print(f"Direct request failed: {e}")
