import sys
import os
import json
import glob
import pathlib
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure pillar1 package path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "pillar1")))

import config
from main import build_lead_card


def _run(cmd: list[str]) -> int:
    return subprocess.run(cmd, check=False).returncode


def find_partial(keyword: str):
    safe = keyword.replace(" ", "_").replace("/", "_").replace("\\", "_").lower().strip("_") or "partial"
    matches = glob.glob(os.path.join("output", f"partial_{safe}_*.json"))
    if not matches:
        return None
    matches.sort(key=os.path.getmtime, reverse=True)
    return matches[0]


def main(keyword: str, partial_path: str | None = None):
    if not partial_path:
        partial_path = find_partial(keyword)
    if not partial_path or not os.path.exists(partial_path):
        print("No partial snapshot found for keyword.")
        return 1

    with open(partial_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    companies = data.get("accumulator", [])
    if not companies:
        print("Partial snapshot has no accumulator entries.")
        return 1

    print(f"Building lead cards from partial snapshot: {partial_path} ({len(companies)} companies)")

    # Build lead cards in parallel
    leads = []
    max_workers = getattr(config, "MAX_CRAWL_WORKERS", 5)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(build_lead_card, c, keyword): c for c in companies}
        for fut in as_completed(futures):
            try:
                card = fut.result()
                if card:
                    leads.append(card)
            except Exception as e:
                print(f"Error building card: {e}")

    # Write raw output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = keyword.replace(" ", "_").replace("/", "_").replace("\\", "_").lower().strip("_") or "lead"
    output_file = os.path.join(config.RAW_OUTPUT_FOLDER, f"{filename}_{timestamp}.json")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=4, ensure_ascii=False)

    print(f"Raw lead cards written: {output_file} (leads={len(leads)})")

    # Run Pillar 2..4 via existing scripts
    # Step 2: clean_leads.py
    clean_file = os.path.join("output", "clean", os.path.basename(output_file))
    os.makedirs(os.path.dirname(clean_file), exist_ok=True)
    rc = _run([sys.executable, "clean_leads.py", output_file, clean_file])
    if rc != 0:
        print("clean_leads.py failed")
        return rc

    # Step 3: verify_leads.py
    verified_file = os.path.join("output", "verified", os.path.basename(output_file))
    os.makedirs(os.path.dirname(verified_file), exist_ok=True)
    rc = _run([sys.executable, "verify_leads.py", clean_file, verified_file])
    if rc != 0:
        print("verify_leads.py failed")
        return rc

    # Step 4: enrichment_leads.py
    enriched_file = os.path.join("output", "enriched", os.path.basename(output_file))
    os.makedirs(os.path.dirname(enriched_file), exist_ok=True)
    rc = _run([sys.executable, "enrichment_leads.py", verified_file, enriched_file])
    if rc != 0:
        print("enrichment_leads.py failed")
        return rc

    # Step 5: finalize_for_pillar4.py
    final_file = os.path.join("output", "final", os.path.basename(output_file))
    os.makedirs(os.path.dirname(final_file), exist_ok=True)
    rc = _run([sys.executable, "finalize_for_pillar4.py", enriched_file, final_file])
    if rc != 0:
        print("finalize_for_pillar4.py failed")
        return rc

    # Step 6: ETL
    try:
        from pillar_4_pipeline.etl import process_file as run_etl
        run_etl(final_file)
    except Exception as e:
        print(f"ETL failed: {e}")
        return 1

    # Step 7: export
    rc = _run([sys.executable, "pillar_4_pipeline/export.py"])
    if rc != 0:
        print("export.py failed")
        return rc

    print("Continuation complete.")
    return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("keyword", nargs="*", help="Keyword to match partial snapshot")
    p.add_argument("--partial", help="Path to partial snapshot file (optional)")
    args = p.parse_args()
    kw = " ".join(args.keyword).strip()
    if not kw and not args.partial:
        print("Provide a keyword or --partial path")
        sys.exit(1)
    if args.partial:
        rc = main(kw or "partial", args.partial)
    else:
        rc = main(kw)
    sys.exit(rc)
