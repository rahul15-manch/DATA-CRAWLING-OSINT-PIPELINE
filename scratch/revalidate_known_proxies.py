import shutil
from datetime import datetime
import json
import time
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests

known_proxies = [
    "34.87.80.221:30000",
    "47.81.56.193:8888",
    "217.182.203.184:8888",
    "181.39.25.196:8118",
    "52.67.38.58:3128",
    "34.134.231.117:3129",
    "38.55.145.46:1081",
    "59.93.212.55:8881",
    "140.245.238.56:53",
    "117.236.124.166:3128",
    "144.24.102.225:8888",
    "153.80.240.37:8080",
    "70.35.196.194:8087",
    "185.230.190.195:3128",
    "210.8.69.102:808",
    "91.99.146.21:8881",
    "108.174.194.34:10801",
    "103.167.61.162:3128",
    "34.94.46.8:80",
    "80.87.195.84:2080",
    "95.182.115.33:1080",
    "14.225.240.23:8562",
    "146.19.169.212:1081",
    "172.171.83.26:8080",
    "3.15.101.97:443",
    "185.196.61.251:8081",
    "47.245.117.43:80",
    "149.18.81.114:7890",
    "140.82.62.31:50000",
    "186.241.90.120:7890"
]

# Deduplicate
known_proxies = list(set(known_proxies))

def test_proxy(proxy):
    url = f"http://{proxy}"
    proxies = {"http": url, "https": url}
    t0 = time.time()
    try:
        resp = requests.get(
            "https://httpbin.org/ip",
            proxies=proxies,
            timeout=8,
            impersonate="chrome",
            verify=False
        )
        latency = (time.time() - t0) * 1000
        if resp.status_code == 200:
            print(f"[OK] {proxy} (Latency: {latency:.0f}ms)")
            return proxy
    except Exception:
        pass
    return None

print(f"Testing {len(known_proxies)} historically working proxies...")
working = []
with ThreadPoolExecutor(max_workers=10) as executor:
    results = executor.map(test_proxy, known_proxies)
    for r in results:
        if r:
            working.append(r)

print(f"\nFound {len(working)} working proxies today.")
if working:
    with open("working_proxies.txt", "w") as f:
        for p in working:
            f.write(f"{p}\n")
    print("Updated working_proxies.txt successfully.")
else:
    print("WARNING: No working proxies found. Restoring original list as fallback.")
    # Fallback to the original 6
    original = [
        "34.87.80.221:30000",
        "47.81.56.193:8888",
        "217.182.203.184:8888",
        "181.39.25.196:8118",
        "52.67.38.58:3128",
        "34.134.231.117:3129"
    ]
    with open("working_proxies.txt", "w") as f:
        for p in original:
            f.write(f"{p}\n")
