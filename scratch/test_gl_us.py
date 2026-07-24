import sys
sys.path.insert(0, ".")
from pillar3_network_resilience.network.client import NetworkClient

def test():
    client = NetworkClient()
    
    url1 = "https://www.google.com/search?q=automation+company&num=5"
    url2 = "https://www.google.com/search?q=automation+company&num=5&hl=en&gl=us"
    
    print("Testing without hl/gl")
    r1 = client.get(url1, session_id=None)
    print("enablejs in r1:", "/httpservice/retry/enablejs" in r1.text)
    
    print("Testing with hl/gl")
    r2 = client.get(url2, session_id=None)
    print("enablejs in r2:", "/httpservice/retry/enablejs" in r2.text)

if __name__ == "__main__":
    test()
