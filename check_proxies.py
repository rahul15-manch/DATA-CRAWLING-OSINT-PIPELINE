import threading
import queue
import requests

q = queue.Queue()
valid_proxies = []

with open("proxies.txt", "r") as f:
    proxies = f.read().split("\n")
    for p in proxies:
        if p.strip():
            q.put(p.strip())


def check_proxies():
    global q

    while not q.empty():
        proxy = q.get()

        try:
            res = requests.get(
                "http://ipinfo.io/json",
                proxies={
                    "http": proxy,
                    "https": proxy
                },
                timeout=5
            )

            if res.status_code == 200:
                print(f" {proxy}")
                valid_proxies.append(proxy)

        except Exception:
            continue


# Create 10 threads
for _ in range(10):
    threading.Thread(target=check_proxies).start()