import re
import sys
sys.path.insert(0, ".")
from pillar3.network.client import NetworkClient

def test_enablejs_bypass():
    client = NetworkClient()
    url = "https://www.google.com/search?q=automation+company&num=5&hl=en&gl=us"
    print("Initial request to:", url)
    resp = client.get(url, session_id="test_session")
    html = resp.text
    
    if "/httpservice/retry/enablejs" in html:
        print("Blocked by enablejs. Attempting bypass...")
        match = re.search(r'url=(/httpservice/retry/enablejs\?sei=[^"]+)', html)
        if match:
            redirect_url = "https://www.google.com" + match.group(1).replace("&amp;", "&")
            print("Found redirect URL:", redirect_url)
            
            # Make the redirect request
            r_resp = client.get(redirect_url, session_id="test_session")
            print("Redirect response status:", r_resp.status_code)
            
            # Retry original
            print("Retrying original request...")
            retry_resp = client.get(url, session_id="test_session")
            
            print("Retry length:", len(retry_resp.text))
            if "/httpservice/retry/enablejs" in retry_resp.text:
                print("Still blocked!")
            elif 'class="g"' in retry_resp.text or 'class="yuRUbf"' in retry_resp.text:
                print("SUCCESS: Found organic results!")
            else:
                print("No organic results, but not enablejs. Saving to debug...")
                with open("debug_retry.html", "w") as f:
                    f.write(retry_resp.text)
        else:
            print("Could not find redirect URL in HTML.")
            print(html[:500])
    else:
        print("Not blocked initially.")
        if 'class="g"' in html or 'class="yuRUbf"' in html:
            print("SUCCESS: Found organic results!")

if __name__ == "__main__":
    test_enablejs_bypass()
