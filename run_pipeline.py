import importlib.util
import os
import sys
import types

# Ensure pillar1 is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "pillar1")))

import pathlib
import subprocess
import time
import config


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


def _resolve_raw_file(result, keyword: str) -> pathlib.Path:
    """Resolve either the legacy raw-file path or main.run_pipeline's lead list."""
    if isinstance(result, (list, tuple)):
        safe = keyword.replace(" ", "_").replace("/", "_").replace("\\", "_").lower().strip("_") or "lead"
        candidates = sorted(
            [p for p in pathlib.Path(config.RAW_OUTPUT_FOLDER).glob(f"{safe}_*.json") if not p.name.endswith("_discovery_report.json")],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError("Pillar 1 returned lead cards but no raw output file was created.")
        return candidates[0]
    return pathlib.Path(result)


def run(keyword: str, disable_cache: bool = False) -> None:
    TOTAL_STEPS = 7
    start_time = time.monotonic()
    stage_timings = {}

    if disable_cache:
        os.environ["ENABLE_SEARCH_CACHE"] = "False"
        os.environ["CACHE_ENABLED"] = "False"
        os.environ["FORCE_LIVE_SEARCH"] = "True"
        # config is imported by this CLI module before argument parsing, so the
        # in-memory values must be changed as well as the environment.
        config.CACHE_ENABLED = False
        config.ENABLE_SEARCH_CACHE = False
        config.FORCE_LIVE_SEARCH = True
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
    stage_started = time.monotonic()

    # Import Pillar 1 here only — this is the orchestrator's boundary.
    # Pillar 2 scripts are NOT imported; they run as subprocesses.
    from main import run_pipeline as pillar1_run
    raw_file_str = pillar1_run(keyword)

    if not raw_file_str:
        print("  NO_MATCH: Search completed successfully but no qualified companies were found.")
        print("  No downstream cleaning, verification, enrichment, or Pillar 4 export was required.")
        return

    raw_file = _resolve_raw_file(raw_file_str, keyword)
    stage_timings["pillar1"] = round(time.monotonic() - stage_started, 3)
    _require_file(raw_file, "clean_leads.py")
    _ok("Raw lead cards created", raw_file)

    # ── Step 2: Clean ─────────────────────────────────────────────────────────
    _step(2, TOTAL_STEPS, "Cleaning leads — remove junk, deduplicate")
    stage_started = time.monotonic()

    clean_file = _derive_next(raw_file, "clean")
    rc = _run("clean_leads.py", [sys.executable, "clean_leads.py", str(raw_file), str(clean_file)])
    if rc != 0:
        _fail("clean_leads.py", rc)
        sys.exit(rc)

    _require_file(clean_file, "verify_leads.py")
    _ok("Clean leads written", clean_file)
    stage_timings["clean"] = round(time.monotonic() - stage_started, 3)

    # ── Step 3: Verify ────────────────────────────────────────────────────────
    _step(3, TOTAL_STEPS, "Verifying leads — DNS, phone, website reachability")
    stage_started = time.monotonic()

    verified_file = _derive_next(clean_file, "verified")
    rc = _run("verify_leads.py", [sys.executable, "verify_leads.py", str(clean_file), str(verified_file)])
    if rc != 0:
        _fail("verify_leads.py", rc)
        sys.exit(rc)

    _require_file(verified_file, "enrichment_leads.py")
    _ok("Verified leads written", verified_file)
    stage_timings["verify"] = round(time.monotonic() - stage_started, 3)

    # ── Step 4: Enrich ────────────────────────────────────────────────────────
    _step(4, TOTAL_STEPS, "Enriching leads — domain guessing, WHOIS")
    stage_started = time.monotonic()

    enriched_file = _derive_next(verified_file, "enriched")
    rc = _run("enrichment_leads.py", [sys.executable, "enrichment_leads.py", str(verified_file), str(enriched_file)])
    if rc != 0:
        _fail("enrichment_leads.py", rc)
        sys.exit(rc)

    _require_file(enriched_file, "finalize_for_pillar4.py")
    _ok("Enriched leads written", enriched_file)
    stage_timings["enrich"] = round(time.monotonic() - stage_started, 3)

    # ── Step 5: Finalize ──────────────────────────────────────────────────────
    _step(5, TOTAL_STEPS, "Finalizing — swap verified contacts, strip debug fields")
    stage_started = time.monotonic()

    final_file = _derive_next(enriched_file, "final")
    rc = _run("finalize_for_pillar4.py", [sys.executable, "finalize_for_pillar4.py", str(enriched_file), str(final_file)])
    if rc != 0:
        _fail("finalize_for_pillar4.py", rc)
        sys.exit(rc)

    _require_file(final_file, "output")
    _ok("Final leads written", final_file)
    stage_timings["finalize"] = round(time.monotonic() - stage_started, 3)

    # ── Step 6: Pillar 4 ETL ──────────────────────────────────────────────────
    _step(6, TOTAL_STEPS, "Pillar 4 ETL — validation, schema alignment, and historical deduplication")
    stage_started = time.monotonic()

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
    stage_timings["pillar4_etl"] = round(time.monotonic() - stage_started, 3)

    # ── Step 7: Pillar 4 Database Export ──────────────────────────────────────
    _step(7, TOTAL_STEPS, "Pillar 4 Database Export — SQLite storage for voice/outreach synchronization")
    stage_started = time.monotonic()

    rc = _run("export.py", [sys.executable, "pillar_4_pipeline/export.py"])
    if rc != 0:
        _fail("export.py", rc)
        sys.exit(rc)

    leads_db_file = pathlib.Path("leads.db")
    _require_file(leads_db_file, "leads.db")
    _ok("SQLite leads database written", leads_db_file)
    stage_timings["pillar4_export"] = round(time.monotonic() - stage_started, 3)

    # ── Summary & Dashboard ───────────────────────────────────────────────────
    elapsed_time = time.monotonic() - start_time
    from stats.dashboard import render_dashboard
    render_dashboard(elapsed_time, keyword)
    print("PIPELINE STAGE TIMINGS (seconds):")
    print(f"  Pillar 1 / enrichment : {stage_timings.get('pillar1', 0.0):.3f}")
    print(f"  Pillar 4 ETL           : {stage_timings.get('pillar4_etl', 0.0):.3f}")
    print(f"  Pillar 4 export         : {stage_timings.get('pillar4_export', 0.0):.3f}")
    print(f"  Total CLI runtime       : {elapsed_time:.3f}")

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
    import argparse
    parser = argparse.ArgumentParser(description="Pillar 1 Discovery Pipeline")
    parser.add_argument("keyword", nargs="*", help="Keyword for discovery")
    parser.add_argument("--no-cache", action="store_true", help="Bypass search cache")
    parser.add_argument("--target-leads", type=int, default=10, help="Target lead count threshold (default: 10, 0=unlimited)")
    
    args, unknown = parser.parse_known_args()
    disable_cache = args.no_cache
    target_leads = args.target_leads
    
    import config
    setattr(config, "TARGET_LEADS_LIMIT", target_leads)
    setattr(config, "TARGET_COMPANIES", target_leads if target_leads > 0 else 999999)
    setattr(config, "TARGET_HIGH_CONFIDENCE", target_leads if target_leads > 0 else 999999)

    kw = " ".join(args.keyword).strip()
    if not kw:
        kw = input("Enter keyword: ").strip()

    if not kw:
        print("Keyword required.")
        sys.exit(1)

    run(kw, disable_cache=disable_cache)
