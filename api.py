"""
FastAPI Backend Server for Lead Discovery & Extraction OSINT Pipeline
Provides live multi-stage status tracking and SQLite leads.db querying.
"""

import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Ensure project root & pillar1 subfolder are on sys.path
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
PILLAR1_PATH = os.path.join(ROOT, "pillar1")
if os.path.exists(PILLAR1_PATH) and PILLAR1_PATH not in sys.path:
    sys.path.insert(0, PILLAR1_PATH)

DB_PATH = os.path.join(ROOT, "leads.db")


def init_db() -> None:
    """
    Ensure the `leads` table exists in leads.db at startup.

    This runs once when the module is imported so that GET /api/leads never
    raises "no such table: leads" on a cold start (i.e. before any pipeline
    run has called _save_leads_to_db).

    The schema here intentionally matches _save_leads_to_db's INSERT columns.
    We use CREATE TABLE IF NOT EXISTS so existing data is never touched.
    Note: flowiz_leads (written by the Pillar-4 SQLiteExporter) lives in the
    same file but is a completely separate table — we do not touch it here.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name     TEXT,
                website          TEXT,
                linkedin         TEXT,
                industry         TEXT,
                location         TEXT,
                contact_page     TEXT,
                about_page       TEXT,
                team_page        TEXT,
                emails           TEXT,
                phones           TEXT,
                social_links     TEXT,
                people           TEXT,
                company_type     TEXT,
                tech_stack       TEXT,
                description      TEXT,
                employees        TEXT,
                founded          TEXT,
                country          TEXT,
                confidence_score REAL,
                lead_quality     TEXT,
                keyword          TEXT,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


# Initialise DB at import time so cold-start reads never fail.
init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Clean startup and shutdown lifecycle management."""
    init_db()
    yield
    # Clean shutdown of Playwright browser manager and pools
    try:
        from pillar1.browser.browser_manager import get_browser_manager
        bm = get_browser_manager()
        bm.shutdown()
    except Exception as exc:
        print(f"[API Lifespan] Browser manager shutdown notice: {exc}")


app = FastAPI(
    title="Lead Discovery & Extraction Dashboard API",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS: support comma-separated origins from environment or default to "*"
raw_cors = os.getenv("CORS_ORIGINS", "*").strip()
if raw_cors == "*" or not raw_cors:
    cors_origins = ["*"]
else:
    cors_origins = [o.strip() for o in raw_cors.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Live Multi-Stage Status Tracking ──────────────────────────────────────────
status_lock = threading.Lock()
pipeline_state = {
    "status": "idle",       # idle | running | completed | error
    "stage": "Ready",        # Human readable stage name
    "stage_code": "IDLE",
    "keyword": "",
    "progress_pct": 0,
    "companies_found": 0,
    "leads_generated": 0,
    "start_time": None,
    "elapsed_sec": 0,
    "error_message": None,
}


def update_stage(stage_code: str, stage_name: str, progress: int, **kwargs):
    """Thread-safe state updater."""
    with status_lock:
        pipeline_state["stage_code"] = stage_code
        pipeline_state["stage"] = stage_name
        pipeline_state["progress_pct"] = progress
        for k, v in kwargs.items():
            if k in pipeline_state:
                pipeline_state[k] = v


def _run_pipeline_bg(keyword: str):
    """Background worker for pipeline execution with granular stage updates."""
    global pipeline_state
    start_t = time.time()
    
    with status_lock:
        pipeline_state.update({
            "status": "running",
            "stage_code": "INIT",
            "stage": "Initializing search environment...",
            "keyword": keyword,
            "progress_pct": 5,
            "companies_found": 0,
            "leads_generated": 0,
            "start_time": start_t,
            "elapsed_sec": 0,
            "error_message": None,
        })

    try:
        # Step 1: Searching Providers
        update_stage("SEARCHING", f"Searching Google & providers for '{keyword}'...", 20)

        # Import pipeline components
        from main import discover_companies, build_company
        from utils.deadline import Deadline
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import config

        # ── Per-request deadline — dynamically loaded from config / env ──────
        max_runtime = float(getattr(config, "MAX_RUNTIME", 120.0))
        discovery_budget = float(getattr(config, "DISCOVERY_DEADLINE_SECONDS", 55.0))
        run_deadline = Deadline(max_runtime)
        discovery_deadline = run_deadline.child(discovery_budget)

        # Step 2: Company Discovery
        update_stage("DISCOVERING", "Discovering and scoring company candidates...", 40)
        companies = discover_companies(keyword, deadline=discovery_deadline)
        found_count = len(companies) if companies else 0

        update_stage(
            "CRAWLING",
            f"Found {found_count} candidates. Crawling homepages & extracting data...",
            60,
            companies_found=found_count
        )

        if not companies:
            update_stage("COMPLETED", "Search completed — 0 candidates found.", 100, status="completed")
            return

        # Step 3: Extraction & Lead Card Construction
        leads = []
        max_workers = getattr(config, "MAX_CRAWL_WORKERS", 4)

        update_stage("EXTRACTING", f"Extracting contact & tech data using {max_workers} workers...", 75)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(build_company, company, keyword, run_deadline): company
                for company in companies
            }
            for future in as_completed(futures):
                try:
                    lead = future.result()
                    if lead is not None:
                        leads.append(lead)
                        with status_lock:
                            pipeline_state["leads_generated"] = len(leads)
                except Exception as exc:
                    print(f"[API Pipeline Error] Error building lead card: {exc}")

        # Step 4: Finalizing & Saving to SQLite DB
        update_stage("SAVING", f"Finalizing {len(leads)} rich lead cards into database...", 90)
        _save_leads_to_db(leads, keyword)
        
        elapsed = round(time.time() - start_t, 2)
        update_stage(
            "COMPLETED",
            f"Successfully generated {len(leads)} lead cards in {elapsed}s",
            100,
            status="completed",
            elapsed_sec=elapsed
        )

    except Exception as e:
        elapsed = round(time.time() - start_t, 2)
        print(f"[API Pipeline Error] {e}")
        with status_lock:
            pipeline_state.update({
                "status": "error",
                "stage_code": "ERROR",
                "stage": f"Error: {str(e)}",
                "error_message": str(e),
                "elapsed_sec": elapsed,
            })


def _save_leads_to_db(leads: list[dict], keyword: str):
    """Save finalized leads into the `leads` table in leads.db.

    The table is guaranteed to exist because init_db() is called at module
    import time.  This function only INSERTs — it never creates or alters
    the schema.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Ensure email_candidates column exists
        try:
            cursor.execute("ALTER TABLE leads ADD COLUMN email_candidates TEXT")
            conn.commit()
        except Exception:
            pass

        for l in leads:
            cursor.execute("""
                INSERT INTO leads (
                    company_name, website, linkedin, industry, location,
                    contact_page, about_page, team_page, emails, email_candidates, phones,
                    social_links, people, company_type, tech_stack, description,
                    employees, founded, country, confidence_score, lead_quality, keyword
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                l.get("company_name"),
                l.get("website"),
                l.get("linkedin"),
                l.get("industry"),
                l.get("location"),
                l.get("contact_page"),
                l.get("about_page"),
                l.get("team_page"),
                json.dumps(l.get("emails", [])),
                json.dumps(l.get("email_candidates", [])),
                json.dumps(l.get("phones", [])),
                json.dumps(l.get("social_links", {})),
                json.dumps(l.get("people", [])),
                l.get("company_type"),
                json.dumps(l.get("tech_stack", [])),
                l.get("description"),
                l.get("employees"),
                l.get("founded"),
                l.get("country"),
                l.get("confidence_score", 0.0),
                l.get("lead_quality", "Low"),
                keyword
            ))
        conn.commit()
        conn.close()
        print(f"[API] Saved {len(leads)} records to SQLite {DB_PATH}")
    except Exception as exc:
        print(f"[API DB Save Error] {exc}")




# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/search")
def start_search(keyword: str = Query(..., min_length=2), bg_tasks: BackgroundTasks = None):
    """Trigger lead discovery and extraction in the background."""
    with status_lock:
        if pipeline_state["status"] == "running":
            return {"error": "A search is already in progress.", "state": pipeline_state}

    bg_tasks.add_task(_run_pipeline_bg, keyword)
    return {"message": "Pipeline execution started", "keyword": keyword}


@app.get("/api/status")
def get_status():
    """Get live multi-stage execution progress."""
    with status_lock:
        state_copy = dict(pipeline_state)
        if state_copy["status"] == "running" and state_copy["start_time"]:
            state_copy["elapsed_sec"] = round(time.time() - state_copy["start_time"], 1)
        return state_copy


@app.get("/api/leads")
def get_leads(category: Optional[str] = None, keyword: Optional[str] = None):
    """Fetch lead cards from SQLite leads.db (with JSON fallback)."""
    leads = []

    # 1. Query SQLite leads.db
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM leads"
            params = []

            conditions = []
            
            if category:
                conditions.append("(LOWER(industry) = LOWER(?) OR LOWER(company_type) = LOWER(?))")
                params.extend([category, category])
            if keyword:
                conditions.append("LOWER(keyword) = LOWER(?)")
                params.append(keyword)
                
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
                
            query += " ORDER BY id DESC LIMIT 100"
            rows = conn.execute(query, params).fetchall()
            
            for r in rows:
                d = dict(r)
                # Deserialize JSON fields
                for jf in ("emails", "email_candidates", "phones", "social_links", "people", "tech_stack"):
                    if d.get(jf):
                        try:
                            d[jf] = json.loads(d[jf])
                        except Exception:
                            pass
                leads.append(d)
            conn.close()
        except Exception as e:
            print(f"[API DB Read Error] {e}")

    # 2. Fallback to newest JSON output file if SQLite returned nothing
    if not leads:
        final_dir = os.path.join(ROOT, "output", "final")
        if os.path.exists(final_dir):
            files = [os.path.join(final_dir, f) for f in os.listdir(final_dir) if f.endswith(".json") and not f.endswith("_dropped.json")]
            if files:
                latest = max(files, key=os.path.getmtime)
                try:
                    with open(latest, "r", encoding="utf-8") as f:
                        leads = json.load(f)
                    if category:
                        leads = [
                            l for l in leads 
                            if (l.get("industry") or l.get("company_type") or "Unknown").lower() == category.lower()
                        ]
                except Exception:
                    pass

    return {"count": len(leads), "leads": leads}


@app.get("/api/categories")
def get_categories():
    """Get category and industry counts for frontend filter tabs."""
    leads_resp = get_leads()
    leads = leads_resp.get("leads", [])
    categories = {}
    for l in leads:
        cat = l.get("industry") or l.get("company_type") or "Unknown"
        if cat and cat != "Unknown":
            categories[cat] = categories.get(cat, 0) + 1
    return {"categories": categories}


@app.get("/health")
def health_check():
    """Standard lightweight health check endpoint for AWS ALB, Nginx, or uptime monitors."""
    with status_lock:
        current_status = pipeline_state.get("status", "idle")
    return {
        "status": "healthy",
        "service": "pillar1-api",
        "pipeline_status": current_status,
        "timestamp": time.time(),
    }


# ── Static File Mount ────────────────────────────────────────────────────────
static_dir = os.path.join(ROOT, "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload_opt = os.getenv("APP_ENV", "development").lower() != "production"
    uvicorn.run("api:app", host=host, port=port, reload=reload_opt)

