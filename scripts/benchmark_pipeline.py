"""
Pipeline Hard-Deadline & Extraction Benchmark Script

Runs 3-5 representative search queries against the discovery & extraction pipeline,
tracking stage timings, hard deadline adherence, company execution stats, field fill rates,
and failure categorization.
"""

import json
import os
import sys
import time
from typing import Dict, List, Any

# Ensure project root & pillar1 subfolder are in sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
PILLAR1_PATH = os.path.join(ROOT, "pillar1")
if os.path.exists(PILLAR1_PATH) and PILLAR1_PATH not in sys.path:
    sys.path.insert(0, PILLAR1_PATH)

from utils.deadline import Deadline, DeadlineExceeded
from discovery.company_discovery import discover_companies
from extraction.page_extractor import extract_from_website
from discovery.contact_discovery import discover_contact
from main import build_lead_card, validate_lead
from concurrent.futures import ThreadPoolExecutor, as_completed


BENCHMARK_QUERIES = [
    "fintech development",
    "custom zomato development",
    "cloud consulting",
]

RUN_BUDGET_SECONDS = 60.0
COMPANY_BUDGET_SECONDS = 15.0


def run_benchmark_for_query(query: str) -> Dict[str, Any]:
    print(f"\n========================================================")
    print(f"  BENCHMARK RUN: '{query}' (Global Budget: {RUN_BUDGET_SECONDS}s)")
    print(f"========================================================")

    start_total = time.monotonic()
    run_deadline = Deadline(RUN_BUDGET_SECONDS)

    # 1. Discovery Stage
    start_disc = time.monotonic()
    disc_secs = min(30.0, run_deadline.remaining())
    disc_deadline = Deadline(disc_secs)
    
    companies = discover_companies(query, deadline=disc_deadline)
    disc_time = round(time.monotonic() - start_disc, 2)
    print(f"[Stage: Discovery] Found {len(companies)} candidates in {disc_time}s")

    # 2. Extraction & Contact Discovery Stage
    start_extract = time.monotonic()
    companies_attempted = len(companies)
    companies_started = 0
    companies_completed = 0
    companies_deadline_skipped = 0
    company_latencies: List[float] = []

    failure_counts = {
        "deadline_exceeded": 0,
        "network_failed": 0,
        "blocked": 0,
        "parser_failed": 0,
        "no_data": 0,
    }

    leads: List[dict] = []

    def _benchmark_worker(company: dict) -> dict | None:
        nonlocal companies_started, companies_completed, companies_deadline_skipped
        t0 = time.monotonic()

        rem_global = run_deadline.remaining()
        if rem_global <= 1.0:
            companies_deadline_skipped += 1
            failure_counts["deadline_exceeded"] += 1
            print(f"[Worker Skip] Skipped {company.get('company')} — global deadline exhausted ({rem_global:.1f}s)")
            return None

        comp_timeout = min(COMPANY_BUDGET_SECONDS, rem_global)
        comp_deadline = Deadline(comp_timeout)
        companies_started += 1

        website = company.get("website") or ""
        name = company.get("company") or ""

        extracted = {}
        contacts = {}
        try:
            if website:
                extracted = extract_from_website(website, deadline=comp_deadline) or {}
        except DeadlineExceeded:
            failure_counts["deadline_exceeded"] += 1
        except Exception as exc:
            err_str = str(exc).lower()
            if "blocked" in err_str or "captcha" in err_str or "403" in err_str:
                failure_counts["blocked"] += 1
            elif "connect" in err_str or "timeout" in err_str or "network" in err_str:
                failure_counts["network_failed"] += 1
            else:
                failure_counts["parser_failed"] += 1

        try:
            if website and not comp_deadline.is_exceeded():
                contacts = discover_contact(website, deadline=comp_deadline) or {}
        except DeadlineExceeded:
            failure_counts["deadline_exceeded"] += 1
        except Exception:
            pass

        dur = round(time.monotonic() - t0, 2)
        company_latencies.append(dur)
        companies_completed += 1

        is_valid, reason = validate_lead(company, extracted)
        if is_valid:
            card = build_lead_card(company, extracted, contacts, keyword=query)
            return card
        else:
            if not extracted:
                failure_counts["no_data"] += 1
            return None

    max_workers = 4
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_benchmark_worker, c): c for c in companies}
        for fut in as_completed(futures):
            try:
                card = fut.result()
                if card:
                    leads.append(card)
            except Exception as e:
                print(f"[Worker Error] {e}")

    extract_time = round(time.monotonic() - start_extract, 2)
    total_time = round(time.monotonic() - start_total, 2)

    # Latency math
    avg_company_s = round(sum(company_latencies) / len(company_latencies), 2) if company_latencies else 0.0
    sorted_lats = sorted(company_latencies)
    p95_idx = int(len(sorted_lats) * 0.95) if sorted_lats else 0
    p95_company_s = round(sorted_lats[p95_idx], 2) if sorted_lats else 0.0

    # Field fill rates
    total_leads = len(leads)
    fields = ["emails", "phones", "location", "country", "employees", "founded", "tech_stack", "people", "description"]
    field_counts = {f: 0 for f in fields}
    
    for l in leads:
        for f in fields:
            val = l.get(f)
            if val and val != "Unknown" and val != [] and val != {}:
                field_counts[f] += 1

    field_fill_rates = {
        f: (f"{round((field_counts[f] / total_leads) * 100, 1)}%" if total_leads > 0 else "0.0%")
        for f in fields
    }

    metrics = {
        "query": query,
        "timings": {
            "total_seconds": total_time,
            "discovery_seconds": disc_time,
            "extraction_seconds": extract_time,
        },
        "companies": {
            "attempted": companies_attempted,
            "started": companies_started,
            "completed": companies_completed,
            "deadline_skipped": companies_deadline_skipped,
            "avg_company_seconds": avg_company_s,
            "p95_company_seconds": p95_company_s,
        },
        "leads_generated": total_leads,
        "field_fill_rates": field_fill_rates,
        "failures": failure_counts,
    }

    return metrics


def main():
    print("=" * 60)
    print("      STARTING PIPELINE HARD-DEADLINE BENCHMARK SUITE")
    print("=" * 60)

    results = []
    for query in BENCHMARK_QUERIES:
        m = run_benchmark_for_query(query)
        results.append(m)

    print("\n" + "=" * 60)
    print("                BENCHMARK SUMMARY MATRIX")
    print("=" * 60)

    summary_json = json.dumps(results, indent=2)
    print(summary_json)

    out_path = os.path.join(ROOT, "benchmark_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary_json)
    print(f"\n[Benchmark] Results saved to: {out_path}")


if __name__ == "__main__":
    main()
