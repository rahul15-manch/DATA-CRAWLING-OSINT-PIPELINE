import sqlite3
import argparse
import json
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DB_FILE = 'leads.db'


def get_db_connection():
    if not os.path.exists(DB_FILE):
        print(f"[ERROR] Database {DB_FILE} not found. Run export_to_db.py first.")
        exit(1)
    conn = sqlite3.connect(DB_FILE)
    # This allows us to access columns by name (returns dictionaries instead of tuples)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_industry(value: str) -> str:
    """FIX #1: must mirror the exact normalization used when the data was
    stored (format_industry in the ETL script): short codes get uppercased
    ('ai' -> 'AI'), longer names get title-cased ('fintech' -> 'Fintech').
    The old version always did .upper(), so any industry longer than 3
    characters could never match what's actually in the DB."""
    if not value:
        return value
    return value.upper() if len(value) <= 3 else value.title()


def safe_json_load(value, default):
    """FIX #2: some rows may have NULL instead of a JSON string (partial
    imports, manual edits, future export scripts that don't guarantee
    '[]'/'{}'). Instead of crashing the whole query for every row, fall
    back to a safe default for just that field."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def format_output(rows):
    """Converts SQLite rows back into clean JSON for Team B"""
    results = []
    for row in rows:
        record = dict(row)
        record['emails'] = safe_json_load(record.get('emails'), [])
        record['phones'] = safe_json_load(record.get('phones'), [])
        record['social_links'] = safe_json_load(record.get('social_links'), {})
        record['people'] = safe_json_load(record.get('people'), [])
        results.append(record)

    print(json.dumps(results, indent=2))
    return results


def search_leads(domain=None, industry=None):
    """Integration Hook: Allows Team B to search the DB dynamically"""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM flowiz_leads WHERE 1=1"
    params = []
    if domain:
        query += " AND domain = ?"
        params.append(domain)
    if industry:
        query += " AND industry = ?"
        params.append(normalize_industry(industry))
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        print(f"[] \n# No leads found matching criteria.")
        return []
    else:
        return format_output(rows)


def generate_quality_matrix():
    """Data Quality Matrix: Generates the DoD Benchmarking Report"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM flowiz_leads")
    total_leads = cursor.fetchone()[0]

    # FIX: also treat NULL as "no email/phone", not just the literal '[]' string,
    # since some rows may have NULL instead of an empty JSON array.
    cursor.execute("SELECT COUNT(*) FROM flowiz_leads WHERE emails IS NOT NULL AND emails != '[]'")
    leads_with_email = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM flowiz_leads WHERE phones IS NOT NULL AND phones != '[]'")
    leads_with_phone = cursor.fetchone()[0]
    conn.close()

    print("\n" + "=" * 40)
    print(" 📊 FLOWIZ DATA QUALITY MATRIX")
    print("=" * 40)
    print(f"Total Unique Verified Leads : {total_leads}")
    if total_leads > 0:
        print(f"Email Coverage Rate         : {round((leads_with_email/total_leads)*100, 1)}%")
        print(f"Phone Coverage Rate         : {round((leads_with_phone/total_leads)*100, 1)}%")
    print("=" * 40)
    if total_leads >= 1000:
        print("✅ DoD MILESTONE REACHED: 1,000+ Leads Extracted")
    else:
        print(f"⚠️ DoD PENDING: Need {1000 - total_leads} more leads to hit 1,000 target.")
    print("=" * 40 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flowiz Data Pipeline CLI & Integration Tool")

    parser.add_argument("--report", action="store_true", help="Generate the Data Quality Matrix report")
    parser.add_argument("--domain", type=str, help="Fetch a specific company by domain (e.g., openai.com)")
    parser.add_argument("--industry", type=str, help="Fetch all companies in a specific industry (e.g., AI)")
    args = parser.parse_args()

    if args.report:
        generate_quality_matrix()
    elif args.domain or args.industry:
        search_leads(domain=args.domain, industry=args.industry)
    else:
        parser.print_help()