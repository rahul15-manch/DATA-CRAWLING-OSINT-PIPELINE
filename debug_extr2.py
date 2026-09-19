import sys, json, os
ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "pillar1"))

from extraction.page_extractor import (
    fetch_page, extract_emails, extract_phone_numbers,
    extract_social_links, extract_structured_contact_info,
    _extract_employees, _extract_employees_from_jsonld,
    _extract_founded, _extract_country,
    extract_people
)
from extraction.tech_detector import detect_tech_stack

# Use a simple, fast, publicly known site
URL = "https://www.infosys.com"
print(f"Fetching {URL} ...")
html = fetch_page(URL)
if not html:
    print("ERROR: fetch_page returned None/empty. Network or robots blocked.")
    sys.exit(1)

print(f"OK - fetched {len(html)} bytes of HTML")

# Run each extractor individually and print results
from bs4 import BeautifulSoup
text = BeautifulSoup(html, "html.parser").get_text(" ")

print("\n--- TECH STACK ---")
print(detect_tech_stack(html, {}))

print("\n--- DESCRIPTION (meta) ---")
import re
desc = ""
for m in re.finditer(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html, re.I):
    desc = m.group(1); break
if not desc:
    for m in re.finditer(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']', html, re.I):
        desc = m.group(1); break
print(repr(desc[:200]))

print("\n--- EMPLOYEES (text regex) ---")
print(repr(_extract_employees(text)))

print("\n--- EMPLOYEES (JSON-LD) ---")
print(repr(_extract_employees_from_jsonld(html)))

print("\n--- FOUNDED ---")
print(repr(_extract_founded(html)))

print("\n--- COUNTRY ---")
print(repr(_extract_country(html, URL)))

print("\n--- SOCIAL LINKS ---")
print(extract_social_links(html, URL))

print("\n--- PEOPLE (homepage) ---")
people = extract_people(html)
print(json.dumps(people[:5], ensure_ascii=False))

print("\n--- STRUCTURED CONTACT ---")
sc = extract_structured_contact_info(html)
print("emails:", sc["emails"])
print("phones:", sc["phones"])
print("location:", sc["location"])

print("\nDone.")
