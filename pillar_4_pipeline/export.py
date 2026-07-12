import sqlite3
import json
import os

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

    # Connect to SQLite (this will create leads.db if it doesn't exist)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Initialize the table
    setup_database(cursor)
    print(f"[INFO] Connected to SQLite database: {DB_FILE}")

    success_count = 0

    # Insert data into the database
    for record in records:
        try:
            # Arrays and Dictionaries must be converted to JSON strings for SQLite
            emails = json.dumps(record.get('emails', []))
            phones = json.dumps(record.get('phones', []))
            social_links = json.dumps(record.get('social_links', {}))
            people = json.dumps(record.get('people', []))

            # INSERT OR REPLACE acts as an Upsert (updates the row if the domain already exists)
            cursor.execute('''
                INSERT OR REPLACE INTO flowiz_leads (
                    domain, company_name, website, industry, location, 
                    contact_page, about_page, emails, phones, social_links, people
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record.get('domain'),
                record.get('company_name'),
                record.get('website'),
                record.get('industry'),
                record.get('location'),
                record.get('contact_page'),
                record.get('about_page'),
                emails,
                phones,
                social_links,
                people
            ))
            success_count += 1
        except Exception as e:
            print(f"[ERROR] Failed to insert {record.get('domain')}: {e}")

    # Save changes and close the connection
    conn.commit()
    conn.close()

    print("-" * 35)
    print("DATABASE EXPORT COMPLETE")
    print("-" * 35)
    print(f"Total Records Exported: {success_count}")
    print(f"Database File Created: {DB_FILE}")
    print("Hand this file to Team B. They can query it immediately.")

if __name__ == "__main__":
    export_data()