from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse
import argparse
import importlib.util
import json
import os
import re
import sys
import types

# Ensure project root and pillar1 subdirectory are in sys.path when run directly
proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)
pillar1_path = os.path.join(proj_root, "pillar1")
if pillar1_path not in sys.path:
    sys.path.insert(0, pillar1_path)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 1. Define the Schema (The Rules)
from models.lead_record import LeadRecord, PersonRecord

Person = PersonRecord

class LeadSchema(LeadRecord):
    """
    LeadSchema for Pillar 4 ETL.
    Inherits from the canonical LeadRecord to guarantee single source of truth
    while preserving backward compatibility with ETL callers.
    """
    model_config = ConfigDict(extra='ignore')

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

            # Merge scalar fields
            for field in [
                'company_name', 'website', 'industry', 'location', 'country', 'employees',
                'founded', 'description', 'contact_page', 'about_page', 'team_page',
                'source', 'source_url', 'lead_score', 'confidence_score', 'confidence',
                'lead_quality', 'relevance_score', 'relevance_tier', 'reason_if_rejected',
            ]:
                if item.get(field) is not None and existing.get(field) is None:
                    existing[field] = item[field]

            if 'emails' in item:
                existing['emails'] = list(set(existing.get('emails', []) + item.get('emails', [])))

            if 'phones' in item:
                existing['phones'] = list(set(existing.get('phones', []) + item.get('phones', [])))

            if 'social_links' in item and isinstance(item.get('social_links'), dict):
                existing.setdefault('social_links', {}).update(item['social_links'])

            if 'people' in item and isinstance(item.get('people'), list):
                existing_people = {
                    (p.get('name') or f"__unnamed_{i}").strip().lower(): p
                    for i, p in enumerate(existing.get('people', []))
                    if isinstance(p, dict)
                }
                for i, person in enumerate(item['people']):
                    if isinstance(person, dict):
                        key = (person.get('name') or f"__unnamed_new_{i}").strip().lower()
                        if key not in existing_people:
                            existing_people[key] = person
                existing['people'] = list(existing_people.values())

            # Merge complex dictionaries
            for dict_field in ['domain_intel', 'org_graph', 'data_quality', 'domain_verification', 'evidence', 'extra_metadata']:
                if item.get(dict_field) and isinstance(item[dict_field], dict):
                    existing.setdefault(dict_field, {}).update(item[dict_field])

            # Merge lists
            if 'tech_stack' in item and isinstance(item.get('tech_stack'), list):
                existing['tech_stack'] = list(set(existing.get('tech_stack', []) + item['tech_stack']))

            if 'emails_provenance' in item and isinstance(item.get('emails_provenance'), list):
                existing.setdefault('emails_provenance', []).extend(item['emails_provenance'])

            if 'phones_provenance' in item and isinstance(item.get('phones_provenance'), list):
                existing.setdefault('phones_provenance', []).extend(item['phones_provenance'])

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