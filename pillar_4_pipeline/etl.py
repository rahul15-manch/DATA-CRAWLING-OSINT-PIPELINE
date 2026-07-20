from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing import List, Optional, Dict
from urllib.parse import urlparse
import json
import os
import re
import argparse
import sys

# Ensure project root is in sys.path when run directly
proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 1. Define the Schema (The Rules)
class Person(BaseModel):
    name: Optional[str] = None
    designation: Optional[str] = None
    linkedin: Optional[str] = None

class LeadSchema(BaseModel):
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
            parsed = urlparse(website)
            if not parsed.netloc:
                parsed = urlparse(f"https://{website}")
            netloc = parsed.netloc.replace('www.', '').lower()
            self.domain = netloc
        return self

OUTPUT_FILE = 'cleaned_data.json'

# --- DECOUPLED PIPELINES ---
class ValidationPipeline:
    def __init__(self):
        self.failed_count = 0

    def __call__(self, item: dict) -> Optional[dict]:
        try:
            from .item_loader import LeadBuilder
            builder = LeadBuilder(item)
            return builder.load_item()
        except Exception as e:
            self.failed_count += 1
            print(f"[WARNING] Record failed validation and was dropped. Reason: {e}")
            return None

class DeduplicationPipeline:
    def __init__(self, master_db: dict):
        self.master_db = master_db
        self.no_domain_count = 0
        self.duplicates_merged = 0

    def __call__(self, item: dict) -> Optional[dict]:
        domain_key = item.get('domain')
        if not domain_key:
            self.no_domain_count += 1
            return None

        if domain_key not in self.master_db:
            self.master_db[domain_key] = item
        else:
            self.duplicates_merged += 1
            existing = self.master_db[domain_key]

            for field in ['company_name', 'industry', 'location', 'contact_page', 'about_page', 'source']:
                if field in item and field not in existing:
                    existing[field] = item[field]

            if 'emails' in item:
                existing['emails'] = list(set(existing.get('emails', []) + item['emails']))

            if 'phones' in item:
                existing['phones'] = list(set(existing.get('phones', []) + item['phones']))

            if 'social_links' in item:
                existing.setdefault('social_links', {}).update(item['social_links'])

            if 'people' in item:
                existing_people = {
                    p.get('name') or f"__unnamed_{i}": p
                    for i, p in enumerate(existing.get('people', []))
                }
                for i, person in enumerate(item['people']):
                    key = person.get('name') or f"__unnamed_new_{i}"
                    existing_people[key] = person
                existing['people'] = list(existing_people.values())

            # Update the item content to be the merged master entry
            item.clear()
            item.update(existing)

        return item

def process_file(input_file: str):
    if not os.path.exists(input_file):
        print(f"[ERROR] Cannot find {input_file}. Make sure the file is in the same directory.")
        return

    print(f"[INFO] Loading raw data from {input_file}...")
    with open(input_file, 'r', encoding='utf-8') as f:
        try:
            raw_records = json.load(f)
        except json.JSONDecodeError:
            print("[ERROR] The input file is not valid JSON.")
            return

    if not isinstance(raw_records, list):
        print("[ERROR] Expected a JSON array (list of objects).")
        return

    master_database = {}

    if os.path.exists(OUTPUT_FILE):
        print(f"[INFO] Found existing {OUTPUT_FILE}. Loading historical records for merging...")
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            try:
                existing_records = json.load(f)
                for record in existing_records:
                    master_database[record['domain']] = record
                print(f"[INFO] Loaded {len(master_database)} existing master records.")
            except json.JSONDecodeError:
                print(f"[WARNING] {OUTPUT_FILE} is empty or unreadable. Starting fresh.")
    else:
        print(f"[INFO] No existing {OUTPUT_FILE} found. Creating a new master list.")

    # Instantiate registry, pipelines, and collector
    from .pipeline_registry import ItemPipelineRegistry
    from .exporters import ItemCollector, ExporterRegistry

    registry = ItemPipelineRegistry()
    val_pipeline = ValidationPipeline()
    dedup_pipeline = DeduplicationPipeline(master_database)

    registry.register(val_pipeline)
    registry.register(dedup_pipeline)

    collector = ItemCollector()
    json_exporter = ExporterRegistry.get_exporter("json", filepath=OUTPUT_FILE)
    if json_exporter:
        collector.register_exporter(json_exporter)

    print(f"[INFO] Processing {len(raw_records)} records...\n")

    for record in raw_records:
        registry.process_item(record)

    # Set final aggregated items to collector for exporting
    final_records = list(master_database.values())
    collector.items = final_records
    collector.close()

    # Final Report
    print("-" * 35)
    print("ETL PIPELINE COMPLETE")
    print("-" * 35)
    print(f"Total Raw Records Ingested: {len(raw_records)}")
    print(f"Unique Master Records Created: {len(final_records)}")
    print(f"Dropped/Failed (validation errors): {val_pipeline.failed_count}")
    print(f"Dropped (no usable domain): {dedup_pipeline.no_domain_count}")
    print(f"Duplicates Merged: {dedup_pipeline.duplicates_merged}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Flowiz ETL Pipeline on a raw data file.")
    parser.add_argument("input_file", help="The raw data file you want to process (e.g., raw_data2.json)")
    args = parser.parse_args()
    process_file(args.input_file)