from fastapi import FastAPI, HTTPException, Query
from typing import Optional
import sqlite3
import json
import os

# Initialize the API
app = FastAPI(
    title="Flowiz Data Pipeline API",
    description="Internal API for querying and bulk-syncing verified B2B/B2C corporate leads.",
    version="1.1.1"
)

DB_FILE = 'leads.db'


def get_db_connection():
    if not os.path.exists(DB_FILE):
        raise HTTPException(status_code=500, detail=f"Database {DB_FILE} not found. Run the ETL exporter first.")
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_industry(value: str) -> str:
    """FIX: mirrors the ETL's format_industry validator exactly - short
    codes get uppercased ('ai' -> 'AI'), longer names get title-cased
    ('fintech' -> 'Fintech'). The old version always did .upper(), so any
    industry name longer than 3 characters could never be found."""
    if not value:
        return value
    return value.upper() if len(value) <= 3 else value.title()


def safe_json_load(value, default):
    """FIX: some rows have NULL instead of a JSON string (e.g. rows
    ingested before the ETL's source/JSON-column fixes were applied).
    Previously a single such row crashed the ENTIRE request, including
    /api/leads/all - meaning one bad row could take down Team B's whole
    startup sync. Now it falls back to a safe empty default per-field."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def parse_lead_rows(rows):
    """Helper function to convert SQLite text arrays back into clean JSON structures"""
    results = []
    for row in rows:
        record = dict(row)
        record['emails'] = safe_json_load(record.get('emails'), [])
        record['phones'] = safe_json_load(record.get('phones'), [])
        record['social_links'] = safe_json_load(record.get('social_links'), {})
        record['people'] = safe_json_load(record.get('people'), [])
        results.append(record)
    return results


@app.get("/", summary="API Root")
def read_root():
    return {
        "message": "Welcome to the Flowiz Data Pipeline API.",
        "status": "Online",
        "endpoints": {
            "bulk_sync_all_leads": "http://127.0.0.1:8000/api/leads/all",
            "filter_leads": "http://127.0.0.1:8000/api/leads",
            "interactive_docs": "http://127.0.0.1:8000/docs"
        }
    }


@app.get("/api/leads/all", summary="Bulk Fetch All Leads")
def get_all_leads():
    """
    Dumps the entire verified database in a single request.
    Team B should use this endpoint at startup to sync all data into memory
    to ensure zero-latency lookups during live voice operations.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM flowiz_leads")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {"status": "success", "count": 0, "data": []}

    processed_data = parse_lead_rows(rows)
    return {"status": "success", "count": len(processed_data), "data": processed_data}


@app.get("/api/leads", summary="Query Specific Leads")
def get_leads(
    domain: Optional[str] = Query(None, description="Filter by exact domain (e.g., openai.com)"),
    industry: Optional[str] = Query(None, description="Filter by industry (e.g., AI)")
):
    """Search endpoint for targeted single-record lookups."""
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
        raise HTTPException(status_code=404, detail="No leads found matching your criteria.")

    processed_data = parse_lead_rows(rows)
    return {"status": "success", "count": len(processed_data), "data": processed_data}