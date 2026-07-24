#!/usr/bin/env python3
"""
proxy_connectivity_check.py
===========================
Live connectivity and proxy diagnostic for the Flowiz network client.

Run: python proxy_connectivity_check.py
"""

import sys
import time

LINE = "=" * 60

def header(title): print(f"\n{LINE}\n  {title}\n{LINE}")
def ok(msg):    print(f"  [OK]   {msg}")
def fail(msg):  print(f"  [FAIL] {msg}")
def warn(msg):  print(f"  [WARN] {msg}")
def info(msg):  print(f"  [INFO] {msg}")

# ─────────────────────────────────────────────────────────────────────────────
# Check 1: curl_cffi
# ─────────────────────────────────────────────────────────────────────────────
header("CHECK 1 — curl_cffi Installation")
try:
    import curl_cffi
    ok(f"curl_cffi installed: version {curl_cffi.__version__}")
    CURL_CFFI_OK = True
except ImportError:
    fail("curl_cffi NOT installed — run: pip install curl_cffi")
    CURL_CFFI_OK = False

# ─────────────────────────────────────────────────────────────────────────────
# Check 2: Network Client import
# ─────────────────────────────────────────────────────────────────────────────
header("CHECK 2 — Network Client Import")
try:
    from pillar3.network import NetworkClient
    from pillar3.network.config import config
    ok("NetworkClient imported successfully")
    ok(f"VERIFY_SSL  : {config.VERIFY_SSL}")
    ok(f"MIN_DELAY   : {config.MIN_DELAY}s  MAX_DELAY: {config.MAX_DELAY}s")
    ok(f"MAX_RETRIES : {config.MAX_RETRIES}")
    NETWORK_CLIENT_OK = True
except Exception as e:
    fail(f"NetworkClient import failed: {e}")
    NETWORK_CLIENT_OK = False

# ─────────────────────────────────────────────────────────────────────────────
# Check 3: Proxy Configuration
# ─────────────────────────────────────────────────────────────────────────────
header("CHECK 3 — Proxy Configuration")
PROXIES_CONFIGURED = False
if NETWORK_CLIENT_OK:
    if config.PROXIES:
        ok(f"{len(config.PROXIES)} proxy/proxies loaded from .env")
        for i, p in enumerate(config.PROXIES, 1):
            display = f"***@{p.split('@')[-1]}" if "@" in p else p
            info(f"  Proxy {i}: {display}")
        PROXIES_CONFIGURED = True
    elif config.PROXY_FILE:
        ok(f"Proxy file: {config.PROXY_FILE}")
        PROXIES_CONFIGURED = True
    else:
        warn("No proxies configured — all requests use your real IP")
        info("Add to .env:  PROXIES=http://user:pass@proxy:port")

# ─────────────────────────────────────────────────────────────────────────────
# Check 4: httpbin — reveals outbound IP (proxy or direct)
# ─────────────────────────────────────────────────────────────────────────────
header("CHECK 4 — Live Connectivity (httpbin.org/ip reveals outbound IP)")
CONNECTIVITY_OK = False
if NETWORK_CLIENT_OK and CURL_CFFI_OK:
    try:
        client = NetworkClient()
        start = time.time()
        resp = client.get("https://httpbin.org/ip", session_id=None)
        latency = (time.time() - start) * 1000
        origin_ip = resp.json().get("origin", "unknown")
        label = "via proxy" if PROXIES_CONFIGURED else "via DIRECT IP (your real IP)"
        ok(f"Connected {label} — Outbound IP: {origin_ip}  ({latency:.0f}ms)")
        CONNECTIVITY_OK = True
    except Exception as e:
        fail(f"httpbin.org failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Check 5: TLS fingerprint check
# ─────────────────────────────────────────────────────────────────────────────
header("CHECK 5 — TLS Fingerprint (should look like Chrome, not Python)")
if NETWORK_CLIENT_OK and CURL_CFFI_OK:
    try:
        client2 = NetworkClient()
        resp = client2.get("https://tls.browserleaks.com/json", session_id=None)
        tls = resp.json()
        ok(f"JA3  hash : {tls.get('ja3_hash', 'unknown')}")
        ok(f"JA3N hash : {tls.get('ja3n_hash', 'unknown')}")
        ua = tls.get("user_agent", "")
        info(f"UA seen   : {ua}")
        if "python" in ua.lower() or "urllib" in ua.lower():
            fail("User-Agent exposed as Python — impersonation NOT working!")
        else:
            ok("User-Agent looks like a real browser to the server")
    except Exception as e:
        warn(f"TLS fingerprint check failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Check 6: Bing
# ─────────────────────────────────────────────────────────────────────────────
header("CHECK 6 — Bing Search Connectivity")
if NETWORK_CLIENT_OK and CURL_CFFI_OK:
    try:
        client3 = NetworkClient()
        start = time.time()
        resp = client3.get("https://www.bing.com/search?q=automation+company&count=3", session_id=None)
        latency = (time.time() - start) * 1000
        if resp.status_code == 200:
            ok(f"Bing: HTTP 200  ({latency:.0f}ms)")
        else:
            fail(f"Bing: HTTP {resp.status_code}  ({latency:.0f}ms)")
    except Exception as e:
        fail(f"Bing failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Check 7: Google (hardest)
# ─────────────────────────────────────────────────────────────────────────────
header("CHECK 7 — Google Search Connectivity (hardest to pass)")
if NETWORK_CLIENT_OK and CURL_CFFI_OK:
    try:
        client4 = NetworkClient()
        start = time.time()
        resp = client4.get("https://www.google.com/search?q=automation+company&num=3", session_id=None)
        latency = (time.time() - start) * 1000
        body = resp.text.lower()
        if resp.status_code == 200:
            if "captcha" in body or "unusual traffic" in body or "consent" in body:
                warn(f"Google HTTP 200 but shows CAPTCHA/consent  ({latency:.0f}ms)")
                warn("Need residential proxies to bypass Google detection")
            else:
                ok(f"Google: HTTP 200 with real results  ({latency:.0f}ms)")
        elif resp.status_code == 429:
            fail(f"Google rate-limited (429) — IP flagged  ({latency:.0f}ms)")
        elif resp.status_code == 403:
            fail(f"Google blocked (403) — IP banned  ({latency:.0f}ms)")
        else:
            warn(f"Google: HTTP {resp.status_code}  ({latency:.0f}ms)")
    except Exception as e:
        fail(f"Google failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Check 8: Proxy pool health
# ─────────────────────────────────────────────────────────────────────────────
header("CHECK 8 — Proxy Pool Health Stats")
if NETWORK_CLIENT_OK:
    try:
        client5 = NetworkClient()
        stats = client5.proxy_manager.get_stats()
        info(f"Total: {stats['total']}  |  Healthy: {stats['healthy']}  |  On cooldown: {stats['cooling_down']}")
        if stats['total'] == 0:
            warn("Proxy pool empty — add proxies to .env to enable rotation")
        elif stats['healthy'] == 0:
            fail("All proxies on cooldown!")
        else:
            ok(f"{stats['healthy']} healthy proxies ready")
    except Exception as e:
        fail(f"Proxy stats failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
header("SUMMARY")
ok("curl_cffi installed") if CURL_CFFI_OK else fail("curl_cffi NOT installed")
ok("NetworkClient imports") if NETWORK_CLIENT_OK else fail("NetworkClient import broken")
ok("Proxies configured") if PROXIES_CONFIGURED else warn("No proxies — using direct IP")
ok("Internet connectivity") if CONNECTIVITY_OK else fail("No connectivity")

if not PROXIES_CONFIGURED:
    print()
    warn("Add residential proxies to .env for reliable Google access:")
    info("  PROXIES=http://user:pass@proxy1.provider.com:8080")

print(f"\n{LINE}\n")
