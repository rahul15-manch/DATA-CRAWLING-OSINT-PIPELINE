from fastapi import FastAPI, HTTPException, Query
from typing import Optional
import os

from database.repository import LeadRepository, normalize_industry
from database.connection import get_default_db_path

# Initialize the API
app = FastAPI(
    title="Flowiz Data Pipeline API",
    description="Internal API for querying and bulk-syncing verified B2B/B2C corporate leads.",
    version="1.2.0"
)

DB_FILE = get_default_db_path()


def get_repo() -> LeadRepository:
    if not os.path.exists(DB_FILE):
        raise HTTPException(status_code=500, detail=f"Database {DB_FILE} not found. Run the ETL exporter first.")
    return LeadRepository(DB_FILE)


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
    repo = get_repo()
    records = repo.get_all_leads()
    processed_data = [r.to_dict() for r in records]
    return {"status": "success", "count": len(processed_data), "data": processed_data}


@app.get("/api/leads", summary="Query Specific Leads")
def get_leads(
    domain: Optional[str] = Query(None, description="Filter by exact domain (e.g., openai.com)"),
    industry: Optional[str] = Query(None, description="Filter by industry (e.g., AI)")
):
    """Search endpoint for targeted single-record lookups."""
    repo = get_repo()
    results = []

    domain_val = domain if isinstance(domain, str) and domain.strip() else None
    industry_val = industry if isinstance(industry, str) and industry.strip() else None

    if domain_val:
        rec = repo.get_lead_by_domain(domain_val)
        if rec:
            norm_ind = normalize_industry(industry_val) if industry_val else None
            if not norm_ind or (rec.industry and rec.industry.lower() == norm_ind.lower()):
                results.append(rec.to_dict())
    else:
        norm_ind = normalize_industry(industry_val) if industry_val else None
        records = repo.get_leads(industry=norm_ind)
        results = [r.to_dict() for r in records]


    if not results:
        raise HTTPException(status_code=404, detail="No leads found matching your criteria.")

    return {"status": "success", "count": len(results), "data": results}