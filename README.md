# DATA-CRAWLING-OSINT-PIPELINE

This repository contains a Python-based lead cleaning and enrichment workflow for OSINT data processing.

## Contents
- Lead cleaning and validation scripts
- JSON datasets used for processing
- Final output files for Pillar 4 workflows

## Getting Started
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the main cleaning pipeline:
   ```bash
   python clean_leads.py
   ```

## Notes
- The repository includes intermediate and final JSON outputs for the pipeline.
- Update the scripts as needed for your own lead-processing workflow.

---

## Pillar 3: Network Resilience & Proxy Infrastructure

This module provides a robust, anti-detect networking client for web scraping.

### Architecture
1. **Concurrency Limiter (Semaphore):** Prevents OS socket exhaustion.
2. **Domain Rate Manager (Token Bucket):** Ensures ethical scraping and evades rate-limit bans.
3. **Entropy Generator:** Injects human-like micro-delays between requests.
4. **Session Manager:** Isolates cookies and maintains connection pools.
5. **Proxy Manager:** Assigns a thread-safe rotating or sticky IP address.
6. **Camouflage Engine (Headers/UA):** Generates strict, mathematically consistent Chrome/TLS fingerprints.
7. **Execution & Telemetry:** Dispatches the request and logs performance securely.
8. **WAF Detector:** Inspects payloads for Datadome, Akamai, or Cloudflare JS challenges.
9. **Retry Engine (Tenacity):** Uses Exponential Backoff + Jitter to silently recover from network failures.

### 🚀 Quick Start (Usage Guide)

#### 1. Configuration (`.env`)
Create a `.env` file in the root directory:
```env
MAX_RETRIES=5
CONNECT_TIMEOUT=5.0
READ_TIMEOUT=15.0
LOG_LEVEL=INFO
# Supply proxies directly or via a file
PROXIES=http://user:pass@proxy1.com:8000,http://user:pass@proxy2.com:8000
```

#### 2. Basic Synchronous Usage
For stateful, multi-step scraping tasks (e.g., Logging into a website):
```python
from network_client_project.network import NetworkClient

client = NetworkClient()

# By providing a session_id, the client guarantees:
# 1. The exact same Proxy IP will be used for both requests.
# 2. Cookies from the login will carry over to the dashboard.
login_resp = client.post("https://target.com/login", session_id="user_123", json={"user": "admin"})
data_resp = client.get("https://target.com/dashboard", session_id="user_123")

print(data_resp.text)
```

#### 3. High-Performance Asynchronous Usage
For massive, parallel data extraction (e.g., fetching 10,000 product URLs):
```python
import asyncio
from network_client_project.network import AsyncNetworkClient

async def fetch_all(urls):
    client = AsyncNetworkClient()
    
    # The client's internal Semaphore safely limits concurrency
    tasks = [client.get(url) for url in urls]
    responses = await asyncio.gather(*tasks)
    
    # Always clean up async connections!
    await client.close_all()
    return responses
```

### 👨‍💻 Developer Guide

If you are modifying the internal network logic, adhere to the following rules:
1. **Never use raw `requests.get()`:** It does not utilize connection pooling. Use the `SessionManager`.
2. **Thread Safety:** All modifications to global state (proxies, rate limits) MUST use `threading.Lock()`.
3. **No Credential Logging:** Ensure `logger.py` masking is active before printing proxy URLs.
4. **Testing:** Run `pytest tests/` before opening a Pull Request.

### 🛡️ Core Evasion Mechanisms

#### TLS Fingerprinting
Standard Python HTTP libraries (`requests`, `httpx`, `aiohttp`) use default OpenSSL fingerprints that are instantly flagged by modern anti-bot systems (Cloudflare, Datadome, Akamai). To bypass this, we use `curl_cffi`, which intercepts the TLS handshake and perfectly impersonates the cipher suites, extensions, and ALPN negotiation of modern browsers (e.g., Chrome 124).

#### Proxy Lifecycle & Rotation
Proxies are central to maintaining network resilience:
- **Sticky Sessions:** Requests sharing a `session_id` are pinned to a specific proxy to maintain state.
- **Auto-Rotation:** Upon network failure or WAF block, the currently active proxy is placed into a cooldown period, and a fresh proxy is immediately rotated in.

#### Intelligent Retry Mechanism
The network engine uses `tenacity` for resilient execution.
- **Exponential Backoff with Jitter:** Prevents thundering herd problems by adding random delays between retries.
