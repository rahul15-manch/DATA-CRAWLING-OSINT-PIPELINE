from __future__ import annotations
import ssl
import socket
from typing import Any

import os
import concurrent.futures

def get_domain_intel(domain: str) -> dict[str, Any]:
    intel: dict[str, Any] = {
        'registrar': None,
        'creation_date': None,
        'country': None,
        'ssl_valid': False,
        'hosting_provider': None,
    }

    if not domain:
        return intel

    clean_domain = domain.lower().replace('https://', '').replace('http://', '').split('/')[0].lstrip('www.')

    # 1. WHOIS Lookup (Guarded: default disabled to avoid Windows WinError 10061 20s socket hang)
    if os.getenv("ENABLE_WHOIS", "false").lower() == "true":
        def _fetch():
            import whois
            return whois.whois(clean_domain)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_fetch)
            w = future.result(timeout=1.5)
            if w:
                intel['registrar'] = getattr(w, 'registrar', None)
                cdate = getattr(w, 'creation_date', None)
                if isinstance(cdate, list):
                    cdate = cdate[0]
                intel['creation_date'] = str(cdate) if cdate else None
                intel['country'] = getattr(w, 'country', None)
        except Exception:
            pass
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    # 2. SSL Certificate check (bounded timeout)
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((clean_domain, 443), timeout=1.5) as sock:
            with ctx.wrap_socket(sock, server_hostname=clean_domain) as ssock:
                cert = ssock.getpeercert()
                if cert:
                    intel['ssl_valid'] = True
                    issuer = dict(x[0] for x in cert.get('issuer', ()))
                    intel['hosting_provider'] = issuer.get('organizationName') or issuer.get('commonName')
    except Exception:
        pass

    return intel

