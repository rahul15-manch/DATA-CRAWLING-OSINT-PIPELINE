# OSINT Network Resilience Client (Pillar 3)

Welcome to the Network Infrastructure module for the Enterprise OSINT & Data Crawling Pipeline. 
This package provides a highly automated, anti-bot resistant, and horizontally scalable HTTP client.

## 🏗 Architecture Overview

The `NetworkClient` acts as a facade, abstracting away the extreme complexity of network evasion. 
When a downstream scraper calls `client.get()`, the request passes through multiple resilient layers:

1. **Concurrency Limiter (Semaphore):** Prevents OS socket exhaustion.
2. **Domain Rate Manager (Token Bucket):** Ensures ethical scraping and evades rate-limit bans.
3. **Entropy Generator:** Injects human-like micro-delays between requests.
4. **Session Manager:** Isolates cookies and maintains connection pools.
5. **Proxy Manager:** Assigns a thread-safe rotating or sticky IP address.
6. **Camouflage Engine (Headers/UA):** Generates strict, mathematically consistent Chrome/TLS fingerprints.
7. **Execution & Telemetry:** Dispatches the request and logs performance securely.
8. **WAF Detector:** Inspects payloads for Datadome, Akamai, or Cloudflare JS challenges.
9. **Retry Engine (Tenacity):** Uses Exponential Backoff + Jitter to silently recover from network failures.

## 🚀 Quick Start (Usage Guide)

### 1. Installation
Install the required dependencies via Pip:
```bash
pip install -r requirements.txt
```

### 2. Configuration (`.env`)
Create a `.env` file in the root directory:
```env
MAX_RETRIES=5
CONNECT_TIMEOUT=5.0
READ_TIMEOUT=15.0
LOG_LEVEL=INFO
# Supply proxies directly or via a file
PROXIES=http://user:pass@proxy1.com:8000,http://user:pass@proxy2.com:8000
```

### 3. Basic Synchronous Usage
For stateful, multi-step scraping tasks (e.g., Logging into a website):
```python
from network import NetworkClient

client = NetworkClient()

# By providing a session_id, the client guarantees:
# 1. The exact same Proxy IP will be used for both requests.
# 2. Cookies from the login will carry over to the dashboard.
login_resp = client.post("https://target.com/login", session_id="user_123", json={"user": "admin"})
data_resp = client.get("https://target.com/dashboard", session_id="user_123")

print(data_resp.text)
```

### 4. High-Performance Asynchronous Usage
For massive, parallel data extraction (e.g., fetching 10,000 product URLs):
```python
import asyncio
from network import AsyncNetworkClient

async def fetch_all(urls):
    client = AsyncNetworkClient()
    
    # The client's internal Semaphore safely limits concurrency
    tasks = [client.get(url) for url in urls]
    responses = await asyncio.gather(*tasks)
    
    # Always clean up async connections!
    await client.close_all()
    return responses
```

## 👨‍💻 Developer Guide

If you are modifying the internal network logic, adhere to the following rules:
1. **Never use raw `requests.get()`:** It does not utilize connection pooling. Use the `SessionManager`.
2. **Thread Safety:** All modifications to global state (proxies, rate limits) MUST use `threading.Lock()`.
3. **No Credential Logging:** Ensure `logger.py` masking is active before printing proxy URLs.
4. **Testing:** Run `pytest tests/` before opening a Pull Request.

## 🚢 Deployment Guide

This package is designed to run in a containerized environment (Docker/Kubernetes).
1. Ensure the `logs/` directory is mounted to an external volume, otherwise logs will be destroyed on pod restart.
2. Adjust `MAX_CONNECTIONS` in the `AsyncNetworkClient` based on the CPU/RAM limits of your specific Kubernetes Pod.
