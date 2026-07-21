import os
import sys
# Add the 'pillar1' subdirectory to sys.path so packages like 'search' and 'query' can be found
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "pillar1")))

import pathlib
import subprocess
import time


def _step(n: int, total: int, label: str) -> None:
    print()
    print(f"[{n}/{total}] {label}...")
    print("-" * 50)


def _ok(label: str, path: pathlib.Path) -> None:
    print(f"  OK  {label}")
    print(f"       -> {path}")


def _fail(label: str, returncode: int) -> None:
    print()
    print(f"  FAILED  {label}  (exit code {returncode})")
    print("  Pipeline stopped.")


def _run(step_label: str, cmd: list[str]) -> int:
    """Run a subprocess command and return its exit code."""
    result = subprocess.run(cmd, check=False)
    return result.returncode


def _require_file(path: pathlib.Path, step_label: str) -> None:
    """Raise a clear error if a required file doesn't exist before a step."""
    if not path.exists():
        raise FileNotFoundError(
            f"\n[ERROR] Expected input for '{step_label}' not found:\n"
            f"  {path}\n"
            f"The previous step may have produced no output or failed silently."
        )


def _derive_next(current: pathlib.Path, subfolder: str) -> pathlib.Path:
    """Derive the output path for the next stage, keeping the same filename stem."""
    return pathlib.Path("output") / subfolder / current.name


def run(keyword: str, disable_cache: bool = False) -> None:
    TOTAL_STEPS = 7
    start_time = time.time()

    if disable_cache:
        os.environ["ENABLE_SEARCH_CACHE"] = "False"
        os.environ["DISCOVERY_DEBUG"] = "true"

    print()
    print("=" * 60)
    print("  FLOWIZ LEAD GENERATION PIPELINE")
    print("=" * 60)
    print(f"  Keyword : {keyword!r}")
    print("=" * 60)

    # Clear previous rejection stats
    from utils.stats_tracker import clear_rejections
    clear_rejections()

    # ── Step 1: Pillar 1 ──────────────────────────────────────────────────────
    _step(1, TOTAL_STEPS, "Pillar 1 — Discover companies & build lead cards")

    # Import Pillar 1 here only — this is the orchestrator's boundary.
    # Pillar 2 scripts are NOT imported; they run as subprocesses.
    from main import run_pipeline as pillar1_run
    raw_file_str = pillar1_run(keyword)

    if not raw_file_str:
        print("  Pillar 1 returned no output file. Exiting.")
        sys.exit(1)

    raw_file = pathlib.Path(raw_file_str)
    _require_file(raw_file, "clean_leads.py")
    _ok("Raw lead cards created", raw_file)

    # ── Step 2: Clean ─────────────────────────────────────────────────────────
    _step(2, TOTAL_STEPS, "Cleaning leads — remove junk, deduplicate")

    clean_file = _derive_next(raw_file, "clean")
    rc = _run("clean_leads.py", [sys.executable, "clean_leads.py", str(raw_file), str(clean_file)])
    if rc != 0:
        _fail("clean_leads.py", rc)
        sys.exit(rc)

    _require_file(clean_file, "verify_leads.py")
    _ok("Clean leads written", clean_file)

    # ── Step 3: Verify ────────────────────────────────────────────────────────
    _step(3, TOTAL_STEPS, "Verifying leads — DNS, phone, website reachability")

    verified_file = _derive_next(clean_file, "verified")
    rc = _run("verify_leads.py", [sys.executable, "verify_leads.py", str(clean_file), str(verified_file)])
    if rc != 0:
        _fail("verify_leads.py", rc)
        sys.exit(rc)

    _require_file(verified_file, "enrichment_leads.py")
    _ok("Verified leads written", verified_file)

    # ── Step 4: Enrich ────────────────────────────────────────────────────────
    _step(4, TOTAL_STEPS, "Enriching leads — domain guessing, WHOIS")

    enriched_file = _derive_next(verified_file, "enriched")
    rc = _run("enrichment_leads.py", [sys.executable, "enrichment_leads.py", str(verified_file), str(enriched_file)])
    if rc != 0:
        _fail("enrichment_leads.py", rc)
        sys.exit(rc)

    _require_file(enriched_file, "finalize_for_pillar4.py")
    _ok("Enriched leads written", enriched_file)

    # ── Step 5: Finalize ──────────────────────────────────────────────────────
    _step(5, TOTAL_STEPS, "Finalizing — swap verified contacts, strip debug fields")

    final_file = _derive_next(enriched_file, "final")
    rc = _run("finalize_for_pillar4.py", [sys.executable, "finalize_for_pillar4.py", str(enriched_file), str(final_file)])
    if rc != 0:
        _fail("finalize_for_pillar4.py", rc)
        sys.exit(rc)

    _require_file(final_file, "output")
    _ok("Final leads written", final_file)

    # ── Step 6: Pillar 4 ETL ──────────────────────────────────────────────────
    _step(6, TOTAL_STEPS, "Pillar 4 ETL — validation, schema alignment, and historical deduplication")

    try:
        from pillar_4_pipeline.etl import process_file as run_etl
        run_etl(str(final_file))
        rc = 0
    except Exception as e:
        print(f"[ERROR] ETL run failed: {e}")
        rc = 1

    if rc != 0:
        _fail("etl.py", rc)
        sys.exit(rc)

    cleaned_data_file = pathlib.Path("cleaned_data.json")
    _require_file(cleaned_data_file, "cleaned_data.json")
    _ok("ETL Cleaned data written", cleaned_data_file)

    # ── Step 7: Pillar 4 Database Export ──────────────────────────────────────
    _step(7, TOTAL_STEPS, "Pillar 4 Database Export — SQLite storage for voice/outreach synchronization")

    rc = _run("export.py", [sys.executable, "pillar_4_pipeline/export.py"])
    if rc != 0:
        _fail("export.py", rc)
        sys.exit(rc)

    leads_db_file = pathlib.Path("leads.db")
    _require_file(leads_db_file, "leads.db")
    _ok("SQLite leads database written", leads_db_file)

    # ── Summary & Dashboard ───────────────────────────────────────────────────
    elapsed_time = time.time() - start_time
    from stats.dashboard import render_dashboard
    render_dashboard(elapsed_time, keyword)

    print("-" * 60)
    print("  Folder map:")
    print(f"    raw      -> {raw_file}")
    print(f"    clean    -> {clean_file}")
    print(f"    verified -> {verified_file}")
    print(f"    enriched -> {enriched_file}")
    print(f"    final    -> {final_file}")
    print(f"    master   -> {cleaned_data_file}")
    print(f"    database -> {leads_db_file}")
    print()
    print("  Pillar 4 synchronization successful. leads.db is updated.")
    print("=" * 60)


if __name__ == "__main__":
    argv = sys.argv[1:]
    disable_cache = "--no-cache" in argv
    if disable_cache:
        argv = [arg for arg in argv if arg != "--no-cache"]

    if argv:
        kw = " ".join(argv).strip()
    else:
        kw = input("Enter keyword: ").strip()

    if not kw:
        print("Keyword required.")
        sys.exit(1)

    run(kw, disable_cache=disable_cache)
