import sqlite3
import json
import os
import sys

# Ensure project root is in sys.path when run directly
proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

INPUT_FILE = 'cleaned_data.json'
DB_FILE = 'leads.db'

def setup_database(cursor):
    # Create the table with 'domain' as the Primary Key
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS flowiz_leads (
            domain TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            website TEXT,
            industry TEXT,
            location TEXT,
            contact_page TEXT,
            about_page TEXT,
            emails TEXT,
            phones TEXT,
            social_links TEXT,
            people TEXT
        )
    ''')

def export_data():
    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] Cannot find {INPUT_FILE}. Run your ETL script first.")
        return

    print(f"[INFO] Reading data from {INPUT_FILE}...")
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        records = json.load(f)

    # Use the decoupled SQLiteExporter via registry
    from pillar_4_pipeline.exporters import ExporterRegistry
    exporter = ExporterRegistry.get_exporter("sqlite", db_path=DB_FILE)
    
    print(f"[INFO] Connecting to SQLite database: {DB_FILE} via SQLiteExporter...")
    if exporter:
        exporter.export(records)

    print("-" * 35)
    print("DATABASE EXPORT COMPLETE")
    print("-" * 35)
    print(f"Total Records Exported: {len(records)}")
    print(f"Database File Created: {DB_FILE}")
    print("Hand this file to Team B. They can query it immediately.")

if __name__ == "__main__":
    export_data()