#!/usr/bin/env python3
"""
Pillar 2 — OSINT Stack Integration
Enrichment Script - Optimized for Bulk Production Data
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

# Configurations
INPUT_FILE = "rescue_candidates.json"
OUTPUT_FILE = "enriched_leads.json"
REQUEST_TIMEOUT = 15
MAX_CONCURRENT_REQUESTS = 8  # Connection pooling to prevent crashing
CANDIDATE_TLDS = [".com", ".in", ".co.in", ".io", ".org"]

# Set your Paid Hunter API key here if available
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
    """WHOIS Lookup - Keep synchronous as python-whois doesn't support async natively."""
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
    """
    OSINT Corporate Registry/Social Matching Method.
    Updated with Error Handling for Bulk Data.
    """
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
                await asyncio.sleep(5)  # Slow down if rate limited
    except Exception as e:
        # Silently fail for corporate profile, don't let it stop the whole pipeline
        return {"linkedin": None, "crunchbase": None}
        
    return profiles

async def enrich_record(session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, rec: dict) -> dict:
    """Enriches a single record wrapping it inside a semaphore control block to avoid network flooding."""
    async with semaphore:
        enrichment = {}
        domain = None
        company_name = rec.get("company_name", "")

        # 1. Corporate Registry / Social Profiles Lookup
        social_profiles = await fetch_social_profiles(session, company_name)
        enrichment["corporate_social_profiles"] = social_profiles

        # 2. Domain Resolution / Guessing
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

        # 3. Deep Enrichment (WHOIS & Email APIs)
        if domain:
            # Sync wrapper thread run for WHOIS lookup to maintain async loop health
            enrichment["whois"] = await asyncio.to_thread(whois_lookup, domain)
            
            api_emails = await find_emails_via_api(session, domain)
            if api_emails:
                enrichment["discovered_emails"] = api_emails

        rec["_enrichment"] = enrichment
        return rec

async def process_bulk_leads():
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as fh:
            records = json.load(fh)
    except FileNotFoundError:
        logging.error(f"Input file {INPUT_FILE} not found. Creating a mockup candidate list.")
        records = [{"company_name": "Google"}, {"company_name": "Microsoft", "website": "https://microsoft.com"}]

    logging.info(f"Loaded {len(records)} records. Initializing high-speed async pipeline...")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    
    async with aiohttp.ClientSession() as session:
        tasks = [enrich_record(session, semaphore, rec) for rec in records]
        enriched_records = await asyncio.gather(*tasks)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(enriched_records, fh, indent=2, ensure_ascii=False)

    found_new_domain = sum(1 for r in enriched_records if r["_enrichment"].get("domain_source") == "guessed_and_verified")
    logging.info(f"Bulk Process Finished. Output saved to {OUTPUT_FILE}.")
    logging.info(f"Discovered {found_new_domain} new domains natively.")

if __name__ == "__main__":
    asyncio.run(process_bulk_leads())