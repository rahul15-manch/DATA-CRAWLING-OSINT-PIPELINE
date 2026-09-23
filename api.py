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


from database.connection import setup_database
from database.repository import LeadRepository

def init_db() -> None:
    """
    Ensure the canonical `flowiz_leads` table and legacy `leads` table exist in leads.db.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        setup_database(cursor)
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
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                email_candidates TEXT,
                domain           TEXT,
                domain_intel     TEXT,
                lead_score       INTEGER,
                org_graph        TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


# Initialise DB at import time so cold-start reads never fail.
init_db()



app = FastAPI(
    title="Lead Discovery & Extraction Dashboard API",
    version="1.0.0",
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

        # ── Per-request deadline — isolated from any concurrent request ──────
        run_deadline = Deadline(100.0)
        discovery_deadline = run_deadline.child(40.0)

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
    """Save finalized leads into canonical flowiz_leads via LeadRepository and legacy leads table."""
    try:
        # 1. Authoritative write to flowiz_leads via LeadRepository
        repo = LeadRepository(DB_PATH)
        processed_leads = []
        for l in leads:
            card = dict(l)
            if not card.get("keyword"):
                card["keyword"] = keyword
            processed_leads.append(card)
        repo.bulk_upsert_leads(processed_leads)

        # 2. Legacy table write for complete backward compatibility
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        for col_name, col_type in [
            ("email_candidates", "TEXT"),
            ("domain", "TEXT"),
            ("domain_intel", "TEXT"),
            ("lead_score", "INTEGER"),
            ("org_graph", "TEXT"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE leads ADD COLUMN {col_name} {col_type}")
                conn.commit()
            except Exception:
                pass

        for l in processed_leads:
            cursor.execute("""
                INSERT INTO leads (
                    company_name, website, linkedin, industry, location,
                    contact_page, about_page, team_page, emails, email_candidates, phones,
                    social_links, people, company_type, tech_stack, description,
                    employees, founded, country, confidence_score, lead_quality, keyword,
                    domain, domain_intel, lead_score, org_graph
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                keyword,
                l.get("domain"),
                json.dumps(l.get("domain_intel") or {}),
                l.get("lead_score"),
                json.dumps(l.get("org_graph") or {}),
            ))
        conn.commit()
        conn.close()
        print(f"[API] Saved {len(leads)} records to SQLite {DB_PATH}")
    except Exception as exc:
        print(f"[API DB Save Error] {exc}")




# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/search")
def start_search(keyword: str = Query(..., min_length=2, max_length=200), bg_tasks: BackgroundTasks = None):
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


@app.get("/api/leads/all", summary="Bulk Fetch All Leads")
def get_all_leads():
    """
    Bulk dumps all verified leads from canonical storage flowiz_leads.
    Unified across root API and Pillar 4 API for startup bulk sync.
    """
    repo = LeadRepository(DB_PATH)
    records = repo.get_all_leads()
    data = [r.to_dict() for r in records]
    return {"status": "success", "count": len(data), "data": data}


@app.get("/api/leads")
def get_leads(
    category: Optional[str] = Query(None, max_length=100),
    keyword: Optional[str] = Query(None, max_length=200),
    domain: Optional[str] = Query(None, max_length=253),
    industry: Optional[str] = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Fetch lead cards from canonical flowiz_leads via LeadRepository (with legacy fallback)."""
    # Normalize parameters if invoked directly as Python function with default Query objects
    category = category if isinstance(category, str) else None
    keyword = keyword if isinstance(keyword, str) else None
    domain = domain if isinstance(domain, str) else None
    industry = industry if isinstance(industry, str) else None
    limit = limit if isinstance(limit, int) else 100
    offset = offset if isinstance(offset, int) else 0

    leads = []

    # 1. Query canonical flowiz_leads via repository
    if os.path.exists(DB_PATH):
        try:
            repo = LeadRepository(DB_PATH)
            if domain:
                rec = repo.get_lead_by_domain(domain)
                if rec:
                    if (not category or (rec.industry or rec.company_type or "").lower() == category.lower()) and \
                       (not keyword or keyword.lower() in (rec.keyword or "").lower()):
                        leads = [rec.to_dict()]
            else:
                cat_filter = category or industry
                records = repo.get_leads(category=cat_filter, keyword=keyword, limit=limit, offset=offset)
                leads = [r.to_dict() for r in records]
        except Exception as e:
            print(f"[API DB Read Error] {e}")

    # 2. Fallback to legacy `leads` table if flowiz_leads had no matching rows
    if not leads and os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM leads"
            params = []
            conditions = []

            if domain:
                conditions.append("LOWER(domain) = LOWER(?)")
                params.append(domain)
            if category:
                conditions.append("(LOWER(industry) = LOWER(?) OR LOWER(company_type) = LOWER(?))")
                params.extend([category, category])
            if keyword:
                conditions.append("LOWER(keyword) = LOWER(?)")
                params.append(keyword)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()

            for r in rows:
                d = dict(r)
                for jf in ("emails", "email_candidates", "phones", "social_links", "people", "tech_stack", "domain_intel", "org_graph"):
                    if d.get(jf):
                        try:
                            d[jf] = json.loads(d[jf])
                        except Exception:
                            pass
                leads.append(d)
            conn.close()
        except Exception as e:
            print(f"[API DB Legacy Read Error] {e}")

    # 3. Fallback to newest JSON output file if SQLite returned nothing
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
    repo = LeadRepository(DB_PATH)
    categories = repo.get_categories()
    if not categories:
        leads_resp = get_leads()
        leads = leads_resp.get("leads", [])
        for l in leads:
            cat = l.get("industry") or l.get("company_type") or "Unknown"
            if cat and cat != "Unknown":
                categories[cat] = categories.get(cat, 0) + 1
    return {"categories": categories}



# ── Static File Mount ────────────────────────────────────────────────────────
static_dir = os.path.join(ROOT, "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
