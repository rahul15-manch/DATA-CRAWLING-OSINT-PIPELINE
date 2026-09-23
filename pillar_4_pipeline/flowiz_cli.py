import sqlite3
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from database.repository import LeadRepository, normalize_industry
from database.connection import get_default_db_path


DB_FILE = get_default_db_path()


def get_repo() -> LeadRepository:
    if not os.path.exists(DB_FILE):
        print(f"[ERROR] Database {DB_FILE} not found. Run export_to_db.py first.")
        sys.exit(1)
    return LeadRepository(DB_FILE)


def search_leads(domain=None, industry=None):
    """Integration Hook: Allows Team B to search the DB dynamically via LeadRepository"""
    repo = get_repo()
    results = []

    if domain:
        rec = repo.get_lead_by_domain(domain)
        if rec:
            norm_ind = normalize_industry(industry) if industry else None
            if not norm_ind or (rec.industry and rec.industry.lower() == norm_ind.lower()):
                results.append(rec.to_dict())
    else:
        norm_ind = normalize_industry(industry) if industry else None
        records = repo.get_leads(industry=norm_ind)
        results = [r.to_dict() for r in records]

    if not results:
        print("[] \n# No leads found matching criteria.")
        return []
    else:
        print(json.dumps(results, indent=2))
        return results


def generate_quality_matrix():
    """Data Quality Matrix: Generates the DoD Benchmarking Report using LeadRepository"""
    repo = get_repo()
    stats = repo.get_stats()

    total_leads = stats["total_leads"]
    leads_with_email = stats["leads_with_email"]
    leads_with_phone = stats["leads_with_phone"]

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