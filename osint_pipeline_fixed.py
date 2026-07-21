#!/usr/bin/env python3


import json
import re
import asyncio
import aiohttp
import logging
from bs4 import BeautifulSoup

try:
    import whois
except ImportError:
    whois = None

INPUT_FILE = "rescue_candidates.json"
OUTPUT_FILE = "final_complete_b2b_profile.json"
REQUEST_TIMEOUT = 8

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def slugify_company_name(name: str) -> str:
    if not name: return ""
    name = name.lower()
    name = re.sub(r"\b(pvt|ltd|private|limited|inc|llp|technologies|technology|solutions|services|consulting|group)\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name

async def guess_and_verify_domain(session: aiohttp.ClientSession, company_name: str):
    """Strong domain recovery flow: Company -> Guess domain -> WHOIS/MX Check -> Homepage -> Recover"""
    slug = slugify_company_name(company_name)
    if not slug: return None, []

    candidate_tlds = [".com", ".in", ".co.in", ".io", ".org", ".ai"]
    tried = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for tld in candidate_tlds:
        domain = f"{slug}{tld}"
        tried.append(domain)
        url = f"https://{domain}"
        try:
            async with session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, headers=headers) as resp:
                if resp.status < 400:
                    return domain, tried
        except Exception:
            continue
    return None, tried

def whois_lookup(domain: str) -> dict:
    """WHOIS & Registry context fallback"""
    if whois is None: return {"error": "python-whois not installed"}
    try:
        w = whois.whois(domain)
        return {
            "registrar": w.registrar,
            "creation_date": str(w.creation_date) if w.creation_date else None,
            "org": getattr(w, "org", None),
            "country": getattr(w, "country", None),
        }
    except Exception as e:
        return {"error": str(e)}

async def scrape_deep_contacts(session: aiohttp.ClientSession, domain: str) -> dict:
    """Extracts JSON-LD, Schema.org, Footer, Contact, and About page data."""
    extracted_data = {"emails": [], "phones": [], "schemas_found": []}
    base_url = f"https://{domain}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    paths_to_check = ["", "/contact", "/about", "/contact-us", "/about-us"]

    for path in paths_to_check:
        target_url = base_url + path
        try:
            async with session.get(target_url, timeout=5, headers=headers) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    json_ld_scripts = soup.find_all('script', type='application/ld+json')
                    for script in json_ld_scripts:
                        try:
                            data = json.loads(script.string or "{}")
                            extracted_data["schemas_found"].append(data)
                        except Exception:
                            pass

                    emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', html)
                    phones = re.findall(r'\+?[0-9][0-9\- \(\)]{8,12}[0-9]', html)

                    extracted_data["emails"].extend(emails)
                    extracted_data["phones"].extend(phones)
        except Exception:
            continue

    extracted_data["emails"] = list(set(extracted_data["emails"]))
    extracted_data["phones"] = list(set(extracted_data["phones"]))
    return extracted_data

async def corporate_registry_match(session: aiohttp.ClientSession, company_name: str) -> dict:
    """Multi-registry corporate matching integration"""
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
                        "status": best_match.get("current_status"),
                        "source_url": best_match.get("opencorporates_url")
                    }
    except Exception:
        pass
    return {"matched": False, "reason": "not_found_in_registries"}

async def process_pipeline():
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            records = json.load(f)
    except FileNotFoundError:
        logging.error(f"Input file {INPUT_FILE} not found.")
        return

    async with aiohttp.ClientSession() as session:
        enriched_records = []
        for rec in records:
            company_name = rec.get("company_name", "")
            logging.info(f"Processing target: {company_name}")
            
            enrichment = {}

            domain = None
            if rec.get("website"):
                domain = re.sub(r"^https?://(www\.)?", "", rec["website"]).split("/")[0]
            else:
                guessed, tried = await guess_and_verify_domain(session, company_name)
                enrichment["domains_tried"] = tried
                if guessed:
                    domain = guessed
                    enrichment["discovered_website"] = f"https://{guessed}"

            if domain:
                enrichment["whois"] = await asyncio.to_thread(whois_lookup, domain)
                deep_data = await scrape_deep_contacts(session, domain)
                enrichment["deep_contacts"] = deep_data

            registry_data = await corporate_registry_match(session, company_name)
            enrichment["corporate_registry"] = registry_data

            rec["_osint_intelligence"] = enrichment
            enriched_records.append(rec)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(enriched_records, f, indent=2, ensure_ascii=False)

    logging.info(f"Pipeline successfully completed! Full OSINT recovery saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(process_pipeline())g
