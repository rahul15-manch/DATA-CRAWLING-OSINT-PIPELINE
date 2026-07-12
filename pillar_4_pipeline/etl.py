from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing import List, Optional, Dict
from urllib.parse import urlparse
import json
import os
import re
import argparse
import os

# 1. Define the Schema (The Rules)
class Person(BaseModel):
    # FIX #5: name is no longer required. A person with a designation/linkedin
    # but no confirmed name is still useful data - we don't want a single
    # missing name to nuke the entire company record.
    name: Optional[str] = None
    designation: Optional[str] = None
    linkedin: Optional[str] = None

class LeadSchema(BaseModel):
    # FIX: explicit config so schema drift (unexpected new fields from
    # scrapers) is visible instead of silently swallowed. Set to 'ignore'
    # here since we DO want unknown fields dropped safely, but this makes
    # that a deliberate choice, not an accident.
    model_config = ConfigDict(extra='ignore')

    company_name: str = Field(..., min_length=1)
    website: str
    domain: str = ""
    industry: Optional[str] = None
    location: Optional[str] = None
    contact_page: Optional[str] = None
    about_page: Optional[str] = None
    emails: List[str] = []
    phones: List[str] = []
    social_links: Dict[str, str] = {}
    people: List[Person] = []
    # FIX #4: source was being silently dropped because it wasn't declared.
    source: Optional[str] = None

    @field_validator('industry')
    @classmethod
    def format_industry(cls, v):
        if v:
            return v.upper() if len(v) <= 3 else v.title()
        return v

    @field_validator('emails')
    @classmethod
    def validate_emails(cls, v):
        valid_emails = []
        email_regex = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")
        for email in v:
            clean_email = email.strip().lower()
            if email_regex.match(clean_email):
                valid_emails.append(clean_email)
        return valid_emails

    @field_validator('phones')
    @classmethod
    def validate_phones(cls, v):
        valid_phones = []
        # FIX #3: original regex only checked allowed CHARACTERS, so strings
        # like "-------" (zero digits) passed. We now strip formatting first,
        # then require the remaining digits to be 7-15 chars - the actual
        # substance of a phone number, not just its punctuation shape.
        digit_count_regex = re.compile(r"^\+?\d{7,15}$")
        for phone in v:
            clean_phone = re.sub(r"[\s\-\(\)]", "", phone.strip())
            if digit_count_regex.match(clean_phone):
                valid_phones.append(clean_phone)
        return valid_phones

    @model_validator(mode='after')
    def extract_domain(self):
        if self.website:
            website = self.website.strip()
            # FIX #2: if the scraper handed us a scheme-less URL like
            # "you.com" instead of "https://you.com", urlparse puts it in
            # .path instead of .netloc, silently producing an empty domain.
            # We detect that and retry with a scheme prepended.
            parsed = urlparse(website)
            if not parsed.netloc:
                parsed = urlparse(f"https://{website}")
            # FIX #1: lowercase the domain. "You.com" and "you.com" must
            # dedupe to the same key, or the same company gets duplicated.
            netloc = parsed.netloc.replace('www.', '').lower()
            self.domain = netloc
        return self

# 2. File I/O Configuration
# --- NEW CLI ARGUMENT SETUP ---
parser = argparse.ArgumentParser(description="Run the Flowiz ETL Pipeline on a raw data file.")
parser.add_argument("input_file", help="The raw data file you want to process (e.g., raw_data2.json)")
args = parser.parse_args()

INPUT_FILE = args.input_file
OUTPUT_FILE = 'cleaned_data.json'

def process_file():
    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] Cannot find {INPUT_FILE}. Make sure the file is in the same directory.")
        return

    print(f"[INFO] Loading raw data from {INPUT_FILE}...")
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        try:
            raw_records = json.load(f)
        except json.JSONDecodeError:
            print("[ERROR] The input file is not valid JSON.")
            return

    if not isinstance(raw_records, list):
        print("[ERROR] Expected a JSON array (list of objects).")
        return


    master_database = {}

    # --- THE NEW MERGE LOGIC ---
    # Check if we already have old cleaned data, and load it into memory first
    if os.path.exists(OUTPUT_FILE):
        print(f"[INFO] Found existing {OUTPUT_FILE}. Loading historical records for merging...")
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            try:
                existing_records = json.load(f)
                for record in existing_records:
                    # Use the domain as the key so new data can safely overwrite/merge into it
                    master_database[record['domain']] = record
                print(f"[INFO] Loaded {len(master_database)} existing master records.")
            except json.JSONDecodeError:
                print(f"[WARNING] {OUTPUT_FILE} is empty or unreadable. Starting fresh.")
    else:
        print(f"[INFO] No existing {OUTPUT_FILE} found. Creating a new master list.")
    # ---------------------------
    failed_count = 0
    # FIX (reporting bug): records with no usable domain were being
    # continue'd without incrementing any counter, which silently corrupted
    # the "Duplicates Merged" math at the end. Now they're tracked explicitly.
    no_domain_count = 0

    print(f"[INFO] Processing {len(raw_records)} records...\n")

    # 3. Process and Deduplicate
    for index, record in enumerate(raw_records):
        try:
            clean_lead = LeadSchema(**record)
            db_ready_data = clean_lead.model_dump(exclude_none=True)

            domain_key = db_ready_data.get('domain')
            if not domain_key:
                no_domain_count += 1
                continue

            if domain_key not in master_database:
                master_database[domain_key] = db_ready_data
            else:
                existing = master_database[domain_key]

                for field in ['company_name', 'industry', 'location', 'contact_page', 'about_page', 'source']:
                    if field in db_ready_data and field not in existing:
                        existing[field] = db_ready_data[field]

                if 'emails' in db_ready_data:
                    existing_emails = existing.get('emails', [])
                    merged_emails = list(set(existing_emails + db_ready_data['emails']))
                    if merged_emails: existing['emails'] = merged_emails

                if 'phones' in db_ready_data:
                    existing_phones = existing.get('phones', [])
                    merged_phones = list(set(existing_phones + db_ready_data['phones']))
                    if merged_phones: existing['phones'] = merged_phones

                if 'social_links' in db_ready_data:
                    existing_socials = existing.get('social_links', {})
                    existing_socials.update(db_ready_data['social_links'])
                    if existing_socials: existing['social_links'] = existing_socials

                # FIX: person name can now be None (see Person model), so
                # dict-by-name merging needs a fallback key for nameless
                # people, or they'd all collapse into one `None` entry.
                if 'people' in db_ready_data:
                    existing_people = {
                        p.get('name') or f"__unnamed_{i}": p
                        for i, p in enumerate(existing.get('people', []))
                    }
                    for i, person in enumerate(db_ready_data['people']):
                        key = person.get('name') or f"__unnamed_new_{index}_{i}"
                        existing_people[key] = person
                    if existing_people: existing['people'] = list(existing_people.values())

        except Exception as e:
            failed_count += 1
            print(f"[WARNING] Record {index} failed validation and was dropped. Reason: {e}")

    final_cleaned_records = list(master_database.values())

    # 4. Save the pristine data to a new file
    print(f"\n[INFO] Saving cleaned & deduplicated data to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_cleaned_records, f, indent=2)

    # 5. Final Report
    duplicates_merged = len(raw_records) - len(final_cleaned_records) - failed_count - no_domain_count
    print("-" * 35)
    print("ETL PIPELINE COMPLETE")
    print("-" * 35)
    print(f"Total Raw Records Ingested: {len(raw_records)}")
    print(f"Unique Master Records Created: {len(final_cleaned_records)}")
    print(f"Dropped/Failed (validation errors): {failed_count}")
    print(f"Dropped (no usable domain): {no_domain_count}")
    print(f"Duplicates Merged: {duplicates_merged}")

if __name__ == "__main__":
    process_file()