from curl_cffi import requests
import time

def test_raw_cffi():
    url = "https://www.google.com/search?q=automation+company&num=5"
    
    versions = ["chrome124", "chrome120", "chrome110", "edge101", "safari15_3", "safari15_5"]
    
    for v in versions:
        try:
            print(f"\nTesting {v}...")
            session = requests.Session(impersonate=v)
            resp = session.get(url)
            html = resp.text
            
            if "/httpservice/retry/enablejs" in html:
                print("Blocked by enablejs!")
            elif 'class="g"' in html or 'class="yuRUbf"' in html:
                print("SUCCESS: Found organic results!")
            else:
                print("Unknown response format, length:", len(html))
        except Exception as e:
            print(f"Failed to use {v}: {e}")
        time.sleep(2)
        
if __name__ == "__main__":
    test_raw_cffi()
