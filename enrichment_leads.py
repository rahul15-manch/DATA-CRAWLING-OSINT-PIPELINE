#!/usr/bin/env python3
"""
Pillar 2 — OSINT Stack Integration
Enrichment Script - Fully Fixed & Optimized for Flowiz Master Pipeline Orchestration
"""

import json
import re
import asyncio
import aiohttp
import logging
from bs4 import BeautifulSoup

try:
    import whois  # python-whois package
except ImportError:
    whois = None

# Production File Configuration according to run_pipeline.py conventions
INPUT_FILE = "output/verified/ai_20260720_110057.json" # Auto-resolved from the stream or your current file
OUTPUT_FILE = "output/enriched/enriched_leads.json"
REQUEST_TIMEOUT = 6
CANDIDATE_TLDS = [".com", ".in", ".co.in", ".io", ".org", ".ai"]

# Paid Hunter API Key
HUNTER_API_KEY = "07efc6bcd50e56afe5f128e524755a96c748a5e6" 

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def slugify_company_name(name: str) -> str:
    """Turn 'Cloud Certitude Pvt Ltd' -> 'cloudcertitude'."""
    if not name: return ""
    name = name.lower()
    name = re.sub(r"\b(pvt|ltd|private|limited|inc|llp|technologies|technology|solutions|services|consulting|group)\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name

async def guess_domain(session: aiohttp.ClientSession, company_name: str):
    """Parallel domain guessing using async connection pooling."""
    slug = slugify_company_name(company_name)
    if not slug:
        return None, []

    tried = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LeadEnricher/2.0"}
    
    for tld in CANDIDATE_TLDS:
        candidate = f"{slug}{tld}"
        tried.append(candidate)
        url = f"https://{candidate}"
        
        try:
            async with session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, headers=headers) as resp:
                if resp.status < 400:
                    return candidate, tried
        except Exception:
            continue
    return None, tried

def whois_lookup(domain: str) -> dict:
    """WHOIS Lookup - Synchronous execution thread safe wrapper."""
    if whois is None:
        return {"error": "python-whois not installed"}
    try:
        w = whois.whois(domain)
        return {
            "registrar": w.registrar,
            "creation_date": str(w.creation_date) if w.creation_date else None,
            "org": getattr(w, "org", None),
            "country": getattr(w, "country", None),
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

async def find_emails_via_api(session: aiohttp.ClientSession, domain: str) -> list:
    """Async Hunter.io email finder hook."""
    if not HUNTER_API_KEY or "YOUR_HUNTER_API_KEY" in HUNTER_API_KEY:
        return []
    
    url = "https://api.hunter.io/v2/domain-search"
    params = {"domain": domain, "api_key": HUNTER_API_KEY}
    
    try:
        async with session.get(url, params=params, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status == 200:
                data = await resp.json()
                return [e["value"] for e in data.get("data", {}).get("emails", [])]
            elif resp.status == 429:
                logging.warning(f"Hunter.io Rate limit hit for domain {domain}")
    except Exception:
        pass
    return []

async def fetch_social_profiles(session: aiohttp.ClientSession, company_name: str) -> dict:
    """OSINT Corporate Registry/Social Matching Method via DuckDuckGo HTML Scraper."""
    profiles = {"linkedin": None, "crunchbase": None}
    if not company_name:
        return profiles
        
    search_query = f"{company_name} LinkedIn Crunchbase"
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
    
    try:
        async with session.post(url, data={'q': search_query}, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                links = soup.find_all('a', class_='url')
                
                for link in links:
                    href = link.get('href', '')
                    if "linkedin.com/company/" in href and not profiles["linkedin"]:
                        profiles["linkedin"] = href
                    if "crunchbase.com/organization/" in href and not profiles["crunchbase"]:
                        profiles["crunchbase"] = href
            else:
                logging.warning(f"Got status {resp.status} for {company_name}")
                await asyncio.sleep(2)
    except Exception:
        return {"linkedin": None, "crunchbase": None}
        
    return profiles

async def corporate_registry_match(session: aiohttp.ClientSession, company_name: str) -> dict:
    """Global Corporate Registry verification logic (OpenCorporates Integration)."""
    oc_url = f"https://api.opencorporates.com/v0.7/companies/search?q={company_name}"
    try:
        async with session.get(oc_url, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status == 200:
                data = await resp.json()
                companies = data.get("results", {}).get("companies", [])
                if companies:
                    best_match = companies[0].get("company", {})
                    return {
                        "matched": True,
                        "registry": best_match.get("jurisdiction_code"),
                        "company_number": best_match.get("company_number"),
                        "registered_name": best_match.get("name"),
                        "status": best_match.get("current_status")
                    }
    except Exception:
        pass
    return {"matched": False, "reason": "not_found_in_registries"}

async def enrich_record(session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, rec: dict) -> dict:
    """Enriches a single record using semaphores to prevent network choking."""
    async with semaphore:
        enrichment = {}
        domain = None
        company_name = rec.get("company_name", "")

        # 1. Social Profile Search
        social_profiles = await fetch_social_profiles(session, company_name)
        enrichment["corporate_social_profiles"] = social_profiles

        # 2. Domain Resolution
        if rec.get("website"):
            domain = re.sub(r"^https?://(www\.)?", "", rec["website"]).split("/")[0]
            enrichment["domain_source"] = "existing_website"
        else:
            guessed, tried = await guess_domain(session, company_name)
            enrichment["domains_tried"] = tried
            if guessed:
                domain = guessed
                enrichment["domain_source"] = "guessed_and_verified"
                enrichment["discovered_website"] = f"https://{guessed}"

        # 3. Deep Identity Extraction (WHOIS, Hunter API, and Registries)
        if domain:
            enrichment["whois"] = await asyncio.to_thread(whois_lookup, domain)
            api_emails = await find_emails_via_api(session, domain)
            if api_emails:
                enrichment["discovered_emails"] = api_emails

        registry_data = await corporate_registry_match(session, company_name)
        enrichment["corporate_registry"] = registry_data

        rec["_enrichment"] = enrichment
        return rec

async def process_bulk_leads():
    """Flawless Master-Pipeline Coordinator supporting Dynamic Naming Stacks."""
    import os
    import sys

    # 1. Dynamic File Resolution based on run_pipeline.py arguments
    if len(sys.argv) > 1:
        target_input = sys.argv[1]
        # Dynamically map output naming matrix to match run_pipeline orchestration
        base_name = os.path.basename(target_input)
        global OUTPUT_FILE
        OUTPUT_FILE = os.path.join("output", "enriched", base_name)
    else:
        # Standalone manual fallback layout
        target_input = INPUT_FILE
        if not os.path.exists(target_input) and os.path.exists("output/verified"):
            files = [os.path.join("output/verified", f) for f in os.listdir("output/verified") if f.endswith(".json")]
            if files:
                target_input = max(files, key=os.path.getctime)
        if not target_input or not os.path.exists(target_input):
            target_input = "rescue_candidates.json" if os.path.exists("rescue_candidates.json") else None

    if not target_input or not os.path.exists(target_input):
        logging.error(f"Target vector array not found at location: {target_input}")
        return

    logging.info(f"Loading leads matrix from active stream: {target_input}")
    with open(target_input, "r", encoding="utf-8") as fh:
        records = json.load(fh)

    # Prevent execution on empty datasets gracefully without throwing FileNotFoundError downstream
    if not records:
        logging.warning("Empty records context received. Pre-seeding structure for pipeline continuum.")
        enriched = []
    else:
        print(f"Enriching {len(records)} records (Multi-threaded async network pools initialized)...")
        semaphore = asyncio.Semaphore(5)
        async with aiohttp.ClientSession() as session:
            tasks = [enrich_record(session, semaphore, rec) for rec in records]
            enriched = await asyncio.gather(*tasks)

    # Ensure output tree infrastructure exists
    out_dir = os.path.dirname(OUTPUT_FILE)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(enriched, fh, indent=2, ensure_ascii=False)

    print("\n" + "=" * 50)
    print(f"Production pipeline checkpoint committed to: {OUTPUT_FILE}")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(process_bulk_leads())