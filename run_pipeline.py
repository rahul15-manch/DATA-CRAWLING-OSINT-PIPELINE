
import os
import sys
import pathlib
import subprocess


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def run(keyword: str) -> None:
    TOTAL_STEPS = 5

    print()
    print("=" * 60)
    print("  FLOWIZ LEAD GENERATION PIPELINE")
    print("=" * 60)
    print(f"  Keyword : {keyword!r}")
    print("=" * 60)

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

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Keyword  : {keyword!r}")
    print()
    print("  Folder map:")
    print(f"    raw      -> {raw_file}")
    print(f"    clean    -> {clean_file}")
    print(f"    verified -> {verified_file}")
    print(f"    enriched -> {enriched_file}")
    print(f"    final    -> {final_file}")
    print()
    print("  The final file is ready for Pillar 3 / outreach.")
    print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        kw = " ".join(sys.argv[1:]).strip()
    else:
        kw = input("Enter keyword: ").strip()

    if not kw:
        print("Keyword required.")
        sys.exit(1)

    run(kw)
