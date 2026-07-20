import os
import sys
import time
import shutil
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests

def test_proxy(proxy_url: str):
    """Two-stage proxy validation.
    
    Stage 1: HTTPS connectivity (lightweight endpoint)
    Stage 2: Google capability classification (actual Google probe)
    
    Returns a rich result dict with transport and Google status.
    """
    result = {
        "proxy": proxy_url,
        "dead": False,
        "https_failed": False,
        "bing_status": "blocked",
        "google_status": "blocked",
        "general_status": "blocked",
        "https_latency_ms": None,
        "bing_latency_ms": None,
        "google_latency_ms": None,
        "score": 100,
        # New fields for richer classification
        "transport_status": "unknown",  # ok | timeout | tls_error | connection_error
        "google_capability": "unknown",  # serp | captcha | 429 | timeout | tls_error | connection_error
    }
    
    url = proxy_url if "://" in proxy_url else f"http://{proxy_url}"
    proxies_dict = {"http": url, "https": url}
    
    # ── Stage 1: HTTPS Connectivity ──────────────────────────────────────
    t0 = time.time()
    try:
        resp = requests.get(
            "https://httpbin.org/ip",
            proxies=proxies_dict,
            timeout=10,
            impersonate="chrome",
            verify=False
        )
        latency = (time.time() - t0) * 1000
        if resp.status_code == 200:
            result["general_status"] = "healthy"
            result["https_latency_ms"] = int(round(latency))
            result["transport_status"] = "ok"
        else:
            result["https_failed"] = True
            result["dead"] = True
            result["score"] = 0
            result["transport_status"] = "connection_error"
            return result
    except Exception as e:
        err_str = str(e).lower()
        result["https_failed"] = True
        result["dead"] = True
        result["score"] = 0
        if "timeout" in err_str or "timed out" in err_str:
            result["transport_status"] = "timeout"
        elif "ssl" in err_str or "tls" in err_str or "certificate" in err_str:
            result["transport_status"] = "tls_error"
        else:
            result["transport_status"] = "connection_error"
        return result
        
    # ── Stage 1b: Bing Test ──────────────────────────────────────────────
    t0 = time.time()
    try:
        resp = requests.get(
            "https://www.bing.com/search?q=test",
            proxies=proxies_dict,
            timeout=10,
            impersonate="chrome",
            verify=False
        )
        latency = (time.time() - t0) * 1000
        if resp.status_code == 200 and "bing" in resp.text.lower() and "html" in resp.headers.get("Content-Type", ""):
            html_lower = resp.text.lower()
            if "captcha" in html_lower or "security check" in html_lower or "please complete" in html_lower or "menlo.gutsenv.net" in html_lower or "safeview" in html_lower:
                result["bing_status"] = "blocked"
            else:
                result["bing_status"] = "healthy"
                result["bing_latency_ms"] = int(round(latency))
        else:
            result["bing_status"] = "blocked"
    except Exception:
        result["bing_status"] = "blocked"
        
    # ── Stage 2: Google Capability Classification ────────────────────────
    t0 = time.time()
    try:
        resp = requests.get(
            "https://www.google.com/search?q=test&hl=en",
            proxies=proxies_dict,
            timeout=10,
            impersonate="chrome",
            verify=False
        )
        latency = (time.time() - t0) * 1000
        html = resp.text.lower()
        content_type = resp.headers.get("Content-Type", "")
        
        # Classify Google response
        if resp.status_code == 429:
            result["google_status"] = "blocked"
            result["google_capability"] = "429"
            result["google_latency_ms"] = int(round(latency))
        elif "g-recaptcha" in html or "hcaptcha" in html:
            result["google_status"] = "blocked"
            result["google_capability"] = "captcha"
            result["google_latency_ms"] = int(round(latency))
        elif "/httpservice/retry/enablejs" in html:
            result["google_status"] = "blocked"
            result["google_capability"] = "captcha"
            result["google_latency_ms"] = int(round(latency))
        elif "consent.google.com" in html or "before you continue" in html:
            result["google_status"] = "blocked"
            result["google_capability"] = "captcha"
            result["google_latency_ms"] = int(round(latency))
        elif resp.status_code == 200 and "text/html" in content_type:
            result["google_status"] = "healthy"
            result["google_capability"] = "serp"
            result["google_latency_ms"] = int(round(latency))
        else:
            result["google_status"] = "blocked"
            result["google_capability"] = "captcha"
            result["google_latency_ms"] = int(round(latency))
    except Exception as e:
        err_str = str(e).lower()
        result["google_status"] = "blocked"
        if "timeout" in err_str or "timed out" in err_str:
            result["google_capability"] = "timeout"
        elif "ssl" in err_str or "tls" in err_str or "certificate" in err_str:
            result["google_capability"] = "tls_error"
        else:
            result["google_capability"] = "connection_error"
        
    # ── Scoring (enhanced with Google capability) ────────────────────────
    if result["google_status"] == "healthy" and result["bing_status"] == "healthy":
        result["score"] = 100
    elif result["google_status"] == "healthy":
        result["score"] = 90
    elif result["bing_status"] == "healthy" and result["google_capability"] == "captcha":
        result["score"] = 70   # Bing works, Google blocked but reachable
    elif result["bing_status"] == "healthy":
        result["score"] = 60
    elif result["general_status"] == "healthy":
        result["score"] = 40
    else:
        result["dead"] = True
        result["score"] = 0
        
    return result

def main():
    proxy_file = "proxies.txt"
    if not os.path.exists(proxy_file):
        print(f"Error: {proxy_file} not found in current directory.")
        sys.exit(1)
        
    with open(proxy_file, "r") as f:
        proxies = [line.strip() for line in f if line.strip()]
        
    total_proxies = len(proxies)
    print(f"Loaded {total_proxies} proxies from {proxy_file}...")
    print("Testing concurrently using ThreadPoolExecutor (30 workers)...")
    
    results = []
    
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(test_proxy, p): p for p in proxies}
        
        completed = 0
        for future in as_completed(futures):
            results.append(future.result())
            completed += 1
            if completed % 10 == 0 or completed == total_proxies:
                print(f"  Progress: {completed}/{total_proxies} tested...", end="\r")
    
    print("\nTesting complete. Compiling statistics...")
    
    dead_count = 0
    https_failed_count = 0
    google_blocked_count = 0
    google_serp_count = 0
    google_captcha_count = 0
    google_429_count = 0
    google_timeout_count = 0
    bing_only_count = 0
    fully_working_count = 0
    general_only_count = 0
    
    working_proxies_list = []
    proxy_state = {}
    
    for r in results:
        p_url = r["proxy"]
        if r["dead"]:
            dead_count += 1
            if r["https_failed"]:
                https_failed_count += 1
        else:
            working_proxies_list.append(p_url)
            proxy_state[p_url] = {
                "score": r["score"],
                "google_successes": 1 if r["google_capability"] == "serp" else 0,
                "google_captchas": 1 if r["google_capability"] == "captcha" else 0,
                "google_429s": 1 if r["google_capability"] == "429" else 0,
                "consecutive_failures": 0,
                "dead": False,
                "google_status": r["google_status"],
                "bing_status": r["bing_status"],
                "general_status": r["general_status"],
                # New fields from two-stage validation
                "last_success_ts": time.time() if r["general_status"] == "healthy" else None,
                "last_failure_ts": None,
                "transport_status": r["transport_status"],
                "google_capability": r["google_capability"],
                "latency_samples": [r["https_latency_ms"] / 1000.0] if r["https_latency_ms"] else [],
                "quarantine_until": None,
                "quarantine_step": 0,
                "inactive": False,
                "outcome_history": [],
                "dead_for_google": False,
                "dead_for_bing": False,
                "consecutive_timeouts": {},
            }
            
            # Count Google capability breakdown
            cap = r["google_capability"]
            if cap == "serp":
                google_serp_count += 1
            elif cap == "captcha":
                google_captcha_count += 1
            elif cap == "429":
                google_429_count += 1
            elif cap == "timeout":
                google_timeout_count += 1
            
            if r["google_status"] == "healthy" and r["bing_status"] == "healthy":
                fully_working_count += 1
            elif r["bing_status"] == "healthy":
                bing_only_count += 1
                if r["google_status"] == "blocked":
                    google_blocked_count += 1
            elif r["general_status"] == "healthy":
                general_only_count += 1
                if r["google_status"] == "blocked":
                    google_blocked_count += 1

    # Save to working_proxies
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_filename = f"working_proxies_{timestamp}.txt"
    
    with open(ts_filename, "w") as f:
        for p in working_proxies_list:
            f.write(f"{p}\n")
            
    # Copy latest to working_proxies.txt
    shutil.copy(ts_filename, "working_proxies.txt")
    
    # Save proxy state to JSON
    with open("proxy_state.json", "w") as f:
        json.dump(proxy_state, f, indent=2)
        
    # Save detailed validation report JSON
    with open("validation_report.json", "w") as f:
        json.dump(results, f, indent=2)
        
    print("\n" + "=" * 50)
    print("PROXY VALIDATION METRICS")
    print("=" * 50)
    print(f"Loaded proxies       : {total_proxies}")
    print(f"Dead                 : {dead_count}")
    print(f"  HTTPS failed       : {https_failed_count}")
    print(f"Working              : {len(working_proxies_list)}")
    print(f"  Fully working      : {fully_working_count}")
    print(f"  Bing only          : {bing_only_count}")
    print(f"  General only       : {general_only_count}")
    print("-" * 50)
    print("GOOGLE CAPABILITY BREAKDOWN (working proxies)")
    print("-" * 50)
    print(f"  SERP returned      : {google_serp_count}")
    print(f"  CAPTCHA / blocked  : {google_captcha_count}")
    print(f"  429 rate-limited   : {google_429_count}")
    print(f"  Timeout            : {google_timeout_count}")
    print("-" * 50)
    print(f"Saved to latest      : working_proxies.txt")
    print(f"Backup file          : {ts_filename}")
    print(f"State saved to       : proxy_state.json")
    print(f"Report saved to      : validation_report.json")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    main()
