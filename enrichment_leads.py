#!/usr/bin/env python3

import json
import re
import asyncio
import aiohttp
import logging
from bs4 import BeautifulSoup
import phonenumbers

try:
    import whois
except ImportError:
    whois = None

INPUT_FILE = "output/verified/ai_20260720_110057.json"
OUTPUT_FILE = "output/enriched/enriched_leads.json"
REQUEST_TIMEOUT = 6
CANDIDATE_TLDS = [".com", ".in", ".co.in", ".io", ".org", ".ai"]

import os

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def check_domain_mx(domain: str) -> bool:
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX", lifetime=4)
        return len(answers) > 0
    except Exception:
        return False

def guess_emails_from_domain(domain: str) -> list:
    if not check_domain_mx(domain):
        return []
    
    prefixes = ["info", "hello", "contact", "sales", "support", "admin"]
    return [f"{p}@{domain}" for p in prefixes]

def slugify_company_name(name: str) -> str:
    if not name: return ""
    name = name.lower()
    name = re.sub(r"\b(pvt|ltd|private|limited|inc|llp|technologies|technology|solutions|services|consulting|group)\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name

async def guess_domain(session: aiohttp.ClientSession, company_name: str):
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
                if resp.status < 400 and resp.status != 202:
                    return candidate, tried
                elif resp.status == 202:
                    await asyncio.sleep(1.5)
                    async with session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, headers=headers) as retry_resp:
                        if retry_resp.status < 400:
                            return candidate, tried
        except Exception:
            continue
    return None, tried

def whois_lookup(domain: str) -> dict:
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

async def extract_contacts_from_web_page(session: aiohttp.ClientSession, domain: str) -> tuple:
    emails = set()
    phones = set()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LeadEnricher/2.0"}
    paths = ["", "/contact", "/about", "/contact-us", "/about-us"]
    
    email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    phone_pattern = re.compile(r'(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,5}\)?[\s\-]?)?\d{3,5}[\s\-]?\d{4,6}')

    for path in paths:
        url = f"https://{domain}{path}"
        try:
            async with session.get(url, timeout=4, allow_redirects=True, headers=headers) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                        tag.decompose()
                    clean_text = soup.get_text(separator=' ')
                    
                    matches = email_pattern.findall(clean_text)
                    for email in matches:
                        if not any(email.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp', '.js', '.css']):
                            emails.add(email.lower())
                            
                    raw_phones = phone_pattern.findall(clean_text)
                    for raw_phone in raw_phones:
                        cleaned_num = raw_phone.strip()
                        if len(cleaned_num) >= 8:
                            for region in ["IN", "US", "GB"]:
                                try:
                                    parsed_number = phonenumbers.parse(cleaned_num, region)
                                    if phonenumbers.is_valid_number(parsed_number):
                                        formatted_num = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
                                        phones.add(formatted_num)
                                        break
                                except Exception:
                                    continue
                                    
        except Exception:
            continue
            
    return list(emails), list(phones)

async def fetch_osint_fallbacks(session: aiohttp.ClientSession, company_name: str) -> tuple:
    emails = set()
    phones = set()
    search_query = f"{company_name} contact phone number email address"
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    phone_pattern = re.compile(r'(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,5}\)?[\s\-]?)?\d{3,5}[\s\-]?\d{4,6}')

    try:
        async with session.post(url, data={'q': search_query}, headers=headers, timeout=8) as resp:
            if resp.status == 200:
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                snippets = soup.find_all('a', class_='result__snippet')
                
                for snippet in snippets:
                    snippet_text = snippet.get_text()
                    
                    for email in email_pattern.findall(snippet_text):
                        emails.add(email.lower())
                        
                    for raw_phone in phone_pattern.findall(snippet_text):
                        cleaned_num = raw_phone.strip()
                        if len(cleaned_num) >= 8:
                            for region in ["IN", "US", "GB"]:
                                try:
                                    parsed_number = phonenumbers.parse(cleaned_num, region)
                                    if phonenumbers.is_valid_number(parsed_number):
                                        formatted_num = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
                                        phones.add(formatted_num)
                                        break
                                except Exception:
                                    continue
    except Exception:
        pass
        
    return list(emails), list(phones)

async def fetch_social_profiles(session: aiohttp.ClientSession, company_name: str) -> dict:
    profiles = {"linkedin": None, "crunchbase": None}
    if not company_name:
        return profiles
        
    search_query = f"{company_name} LinkedIn Crunchbase"
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
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
    except Exception:
        pass
        
    return profiles

async def corporate_registry_match(session: aiohttp.ClientSession, company_name: str) -> dict:
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
    async with semaphore:
        enrichment = {}
        domain = None
        company_name = rec.get("company_name", "")

        social_profiles = await fetch_social_profiles(session, company_name)
        enrichment["corporate_social_profiles"] = social_profiles

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

        all_emails = set()
        all_phones = set()

        if domain:
            enrichment["whois"] = await asyncio.to_thread(whois_lookup, domain)
            
            web_emails, web_phones = await extract_contacts_from_web_page(session, domain)
            all_emails.update(web_emails)
            all_phones.update(web_phones)
            
            guessed_domain_emails = guess_emails_from_domain(domain)
            all_emails.update(guessed_domain_emails)
            
            if HUNTER_API_KEY and "YOUR_HUNTER_API_KEY" not in HUNTER_API_KEY:
                try:
                    url = "https://api.hunter.io/v2/domain-search"
                    params = {"domain": domain, "api_key": HUNTER_API_KEY}
                    async with session.get(url, params=params, timeout=REQUEST_TIMEOUT) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            api_emails = [e["value"] for e in data.get("data", {}).get("emails", [])]
                            all_emails.update(api_emails)
                except Exception:
                    pass

        if not all_phones or not all_emails:
            osint_emails, osint_phones = await fetch_osint_fallbacks(session, company_name)
            all_emails.update(osint_emails)
            all_phones.update(osint_phones)

        if not all_emails and domain:
            all_emails.update([f"info@{domain}", f"support@{domain}"])

        enrichment["discovered_emails"] = list(all_emails)
        enrichment["discovered_phones"] = list(all_phones)

        registry_data = await corporate_registry_match(session, company_name)
        enrichment["corporate_registry"] = registry_data

        rec["_enrichment"] = enrichment
        return rec

async def process_bulk_leads():
    import os
    import sys

    if len(sys.argv) > 1:
        target_input = sys.argv[1]
        base_name = os.path.basename(target_input)
        global OUTPUT_FILE
        OUTPUT_FILE = os.path.join("output", "enriched", base_name)
    else:
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

    if not records:
        logging.warning("Empty records context received. Pre-seeding structure for pipeline continuum.")
        enriched = []
    else:
        print(f"Enriching {len(records)} records (Multi-threaded async network pools with Deep Contact Scraping initialized)...")
        semaphore = asyncio.Semaphore(5)
        async with aiohttp.ClientSession() as session:
            tasks = [enrich_record(session, semaphore, rec) for rec in records]
            enriched = await asyncio.gather(*tasks)

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