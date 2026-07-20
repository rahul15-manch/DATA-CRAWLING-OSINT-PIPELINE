#!/usr/bin/env python3
import json
import time
import requests
from bs4 import BeautifulSoup
import re

# Configurations
INPUT_FILE = "enriched_leads.json"
OUTPUT_FILE = "registry_matched_leads.json"
REQUEST_DELAY = 2.0 

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0"}

def is_valid_company(name):
    """Filter: Sirf unhi records ko search karein jo chhote hain (article titles nahi)."""
    if not name: return False
    # Agar company name mein question mark hai ya 6 words se zyada hai, toh skip karein
    if "?" in name or len(name.split()) > 6:
        return False
    return True

def search_registry(company_name):
    """ZaubaCorp se Indian companies ka data fetch karta hai."""
    # ZaubaCorp search URL
    url = f"https://www.zaubacorp.com/company-search/search?search={company_name}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Search result link dhundhein
        link = soup.find("a", href=lambda x: x and "/company/" in x)
        
        if not link:
            return {"matched": False, "reason": "no_result_on_zauba"}
            
        company_url = link['href']
        company_name_found = link.get_text(strip=True)
        
        return {
            "matched": True,
            "registered_name": company_name_found,
            "source_url": company_url
        }
    except Exception as e:
        return {"matched": False, "reason": str(e)}

# Main Execution Loop
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

for entry in data:
    name = entry.get("company_name", "")
    
    # 1. Filter logic apply karein
    if not is_valid_company(name):
        print(f"Skipping (Article Title): {name}...")
        entry["_registry"] = {"matched": False, "reason": "article_title_or_invalid"}
        continue
    
    # 2. Matching logic run karein
    print(f"Registry matching for: {name}...")
    entry["_registry"] = search_registry(name)
    time.sleep(REQUEST_DELAY)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"\nRegistry matching complete! Saved to {OUTPUT_FILE}")