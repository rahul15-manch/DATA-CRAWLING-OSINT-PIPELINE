import hmac
import hashlib
import time
import requests
from urllib.parse import urlencode

def sign_request(method: str, url: str, secret_key: str, payload: dict = None) -> dict:
    """
    Demonstrates how to cryptographically sign a request.
    Many high-security APIs (like Crypto Exchanges or Government Databases)
    require this to prove the request hasn't been tampered with and comes from an authorized client.
    """
    timestamp = str(int(time.time() * 1000))
    
    # Create the base string to sign
    # Format: Timestamp + Method + Path + Body
    from urllib.parse import urlparse
    path = urlparse(url).path
    
    body_str = ""
    if payload:
        # Sort keys to ensure consistency
        body_str = urlencode(sorted(payload.items()))
        
    message = timestamp + method.upper() + path + body_str
    
    # Generate HMAC SHA256 Signature
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Return the security headers
    return {
        "X-API-Timestamp": timestamp,
        "X-API-Signature": signature
    }

if __name__ == "__main__":
    # Demo
    API_SECRET = "super_secret_key_from_aws_secrets_manager"
    target_url = "https://api.securetarget.com/v1/data"
    
    # Generate the signed headers
    security_headers = sign_request("GET", target_url, API_SECRET)
    
    print(f"Generated Security Headers: {security_headers}")
    # You would then merge these headers into your NetworkClient's base headers.
