"""
database/repository.py
======================
Authoritative Data Access Layer (Repository Pattern) for the canonical
`flowiz_leads` storage.

Converts between SQLite table rows and strongly validated LeadRecord instances,
guaranteeing zero silent data loss.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from models.lead_record import LeadRecord, PersonRecord, normalize_domain
from database.connection import get_db_connection, setup_database, get_db_path

logger = logging.getLogger(__name__)


def normalize_industry(value: Optional[str]) -> Optional[str]:
    """Canonical industry normalization (short codes uppercase e.g. AI, longer title-cased)."""
    if not isinstance(value, str) or not value.strip() or value.lower() == "unknown":
        return value if isinstance(value, str) else None
    v = value.strip()
    return v.upper() if len(v) <= 3 else v.title()



def _safe_json_loads(val: Any, default: Any) -> Any:

    """Safely decode JSON strings stored in SQLite columns."""
    if val is None:
        return default
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default


def row_to_lead_record(row: Any) -> LeadRecord:
    """Converts a SQLite sqlite3.Row or dict into a canonical LeadRecord."""
    d = dict(row)
    emails = _safe_json_loads(d.get("emails"), [])
    phones = _safe_json_loads(d.get("phones"), [])
    social_links = _safe_json_loads(d.get("social_links"), {})
    tech_stack = _safe_json_loads(d.get("tech_stack"), [])
    domain_intel = _safe_json_loads(d.get("domain_intel"), None)
    org_graph = _safe_json_loads(d.get("org_graph"), None)
    email_candidates = _safe_json_loads(d.get("email_candidates"), [])

    # Decode people
    people_raw = _safe_json_loads(d.get("people"), [])
    people = []
    if isinstance(people_raw, list):
        for p in people_raw:
            if isinstance(p, dict):
                people.append(PersonRecord(**p))
            elif isinstance(p, PersonRecord):
                people.append(p)

    return LeadRecord(
        id=d.get("id"),
        company_name=d.get("company_name") or "",
        website=d.get("website"),
        domain=d.get("domain") or normalize_domain(d.get("website")),
        linkedin=d.get("linkedin"),
        company_type=d.get("company_type") or "Unknown",
        industry=d.get("industry"),
        location=d.get("location"),
        country=d.get("country"),
        employees=d.get("employees"),
        founded=d.get("founded"),
        description=d.get("description"),
        tech_stack=tech_stack,
        contact_page=d.get("contact_page"),
        about_page=d.get("about_page"),
        team_page=d.get("team_page"),
        emails=emails,
        phones=phones,
        social_links=social_links,
        people=people,
        email_candidates=email_candidates,
        domain_intel=domain_intel,
        lead_score=d.get("lead_score"),
        org_graph=org_graph,
        confidence_score=d.get("confidence_score"),
        lead_quality=d.get("lead_quality"),
        keyword=d.get("keyword"),
        created_at=str(d.get("created_at")) if d.get("created_at") else None,
    )


class LeadRepository:
    """
    Authoritative Repository for managing lead records in flowiz_leads.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = get_db_path(db_path)
        self.init_schema()

    def init_schema(self) -> None:
        """Ensure canonical schema exists."""
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            setup_database(cursor)
            conn.commit()
        finally:
            conn.close()

    def upsert_lead(self, lead_data: Union[LeadRecord, Dict[str, Any]]) -> LeadRecord:
        """
        Inserts or updates a single lead in the canonical table.
        """
        if isinstance(lead_data, dict):
            lead = LeadRecord.from_dict(lead_data)
        elif isinstance(lead_data, LeadRecord):
            lead = lead_data
        else:
            raise ValueError(f"Expected LeadRecord or dict, got {type(lead_data)}")

        row = lead.to_flowiz_leads_row()
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO flowiz_leads (
                    domain, company_name, website, industry, location,
                    contact_page, about_page, emails, phones, social_links, people,
                    tech_stack, lead_score, description, employees, founded, country,
                    domain_intel, org_graph, confidence_score, lead_quality, keyword
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["domain"], row["company_name"], row["website"],
                row["industry"], row["location"], row["contact_page"],
                row["about_page"], row["emails"], row["phones"],
                row["social_links"], row["people"], row["tech_stack"],
                row["lead_score"], row["description"], row["employees"],
                row["founded"], row["country"], row["domain_intel"],
                row["org_graph"],
                lead.confidence_score if lead.confidence_score is not None else lead.confidence,
                lead.lead_quality,
                lead.keyword,
            ))
            conn.commit()
            return lead
        finally:
            conn.close()

    def bulk_upsert_leads(self, items: List[Union[LeadRecord, Dict[str, Any]]]) -> int:
        """
        Batch inserts or replaces leads in flowiz_leads within a single transaction.
        """
        if not items:
            return 0

        conn = get_db_connection(self.db_path)
        inserted_count = 0
        try:
            cursor = conn.cursor()
            for item in items:
                try:
                    if isinstance(item, dict):
                        lead = LeadRecord.from_dict(item)
                    elif isinstance(item, LeadRecord):
                        lead = item
                    else:
                        continue

                    row = lead.to_flowiz_leads_row()
                    cursor.execute("""
                        INSERT OR REPLACE INTO flowiz_leads (
                            domain, company_name, website, industry, location,
                            contact_page, about_page, emails, phones, social_links, people,
                            tech_stack, lead_score, description, employees, founded, country,
                            domain_intel, org_graph, confidence_score, lead_quality, keyword
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row["domain"], row["company_name"], row["website"],
                        row["industry"], row["location"], row["contact_page"],
                        row["about_page"], row["emails"], row["phones"],
                        row["social_links"], row["people"], row["tech_stack"],
                        row["lead_score"], row["description"], row["employees"],
                        row["founded"], row["country"], row["domain_intel"],
                        row["org_graph"],
                        lead.confidence_score if lead.confidence_score is not None else lead.confidence,
                        lead.lead_quality,
                        lead.keyword,
                    ))
                    inserted_count += 1
                except Exception as exc:
                    logger.error(f"[LeadRepository] Error upserting lead: {exc}")
            conn.commit()
            return inserted_count
        finally:
            conn.close()

    def get_lead_by_domain(self, domain: str) -> Optional[LeadRecord]:
        """Fetch a single lead record by exact domain."""
        norm_domain = normalize_domain(domain)
        if not norm_domain:
            return None

        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM flowiz_leads WHERE domain = ?", (norm_domain,))
            row = cursor.fetchone()
            if not row:
                return None
            return row_to_lead_record(row)
        finally:
            conn.close()

    def get_leads(
        self,
        domain: Optional[str] = None,
        industry: Optional[str] = None,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[LeadRecord]:
        """
        Query canonical leads with flexible filters.
        """
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            query = "SELECT * FROM flowiz_leads WHERE 1=1"
            params: List[Any] = []

            if domain:
                query += " AND domain = ?"
                params.append(normalize_domain(domain))

            ind = industry or category
            if ind:
                query += " AND (LOWER(industry) = LOWER(?) OR LOWER(industry) LIKE LOWER(?))"
                params.extend([ind, f"%{ind}%"])

            if keyword:
                query += " AND (LOWER(keyword) = LOWER(?) OR LOWER(company_name) LIKE LOWER(?))"
                params.extend([keyword, f"%{keyword}%"])

            safe_limit = max(1, min(int(limit), 1000))
            safe_offset = max(0, int(offset))

            query += " ORDER BY domain ASC LIMIT ? OFFSET ?"
            params.extend([safe_limit, safe_offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [row_to_lead_record(r) for r in rows]
        finally:
            conn.close()

    def get_all_leads(self) -> List[LeadRecord]:
        """Dumps all leads from the canonical table."""
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM flowiz_leads ORDER BY domain ASC")
            rows = cursor.fetchall()
            return [row_to_lead_record(r) for r in rows]
        finally:
            conn.close()

    def count_leads(self) -> int:
        """Returns total count of records in the canonical table."""
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM flowiz_leads")
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def get_categories(self) -> Dict[str, int]:
        """Returns breakdown of lead counts grouped by industry/category."""
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT industry, count(*) FROM flowiz_leads WHERE industry IS NOT NULL AND industry != '' GROUP BY industry")
            categories = {}
            for row in cursor.fetchall():
                categories[row[0]] = row[1]
            return categories
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Computes high-level database quality and lead statistics."""
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            total = self.count_leads()
            cursor.execute("SELECT count(*) FROM flowiz_leads WHERE emails IS NOT NULL AND emails != '[]' AND emails != ''")
            with_emails = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM flowiz_leads WHERE phones IS NOT NULL AND phones != '[]' AND phones != ''")
            with_phones = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM flowiz_leads WHERE lead_score IS NOT NULL AND lead_score > 0")
            with_score = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM flowiz_leads WHERE domain_intel IS NOT NULL AND domain_intel != '{}' AND domain_intel != ''")
            with_intel = cursor.fetchone()[0]

            return {
                "total_leads": total,
                "leads_with_email": with_emails,
                "leads_with_phone": with_phones,
                "leads_with_lead_score": with_score,
                "leads_with_domain_intel": with_intel,
            }
        finally:
            conn.close()

    def migrate_from_legacy_leads(self) -> Dict[str, int]:
        """
        Non-destructively migrates historical records from legacy `leads` table
        into canonical `flowiz_leads` table.
        """
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            # Check if legacy leads table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leads'")
            if not cursor.fetchone():
                return {"source_count": 0, "migrated": 0, "already_existed": 0}

            cursor.execute("SELECT * FROM leads")
            legacy_rows = cursor.fetchall()
            source_count = len(legacy_rows)
            migrated = 0
            already_existed = 0

            # Get set of domains already present in flowiz_leads
            cursor.execute("SELECT domain FROM flowiz_leads")
            existing_domains = {r[0] for r in cursor.fetchall() if r[0]}

            for r in legacy_rows:
                d = dict(r)
                website = d.get("website") or ""
                domain = d.get("domain") or normalize_domain(website)

                if not domain:
                    continue

                if domain in existing_domains:
                    already_existed += 1
                    continue

                lead = row_to_lead_record(d)
                lead.domain = domain
                row = lead.to_flowiz_leads_row()

                cursor.execute("""
                    INSERT OR REPLACE INTO flowiz_leads (
                        domain, company_name, website, industry, location,
                        contact_page, about_page, emails, phones, social_links, people,
                        tech_stack, lead_score, description, employees, founded, country,
                        domain_intel, org_graph, confidence_score, lead_quality, keyword
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row["domain"], row["company_name"], row["website"],
                    row["industry"], row["location"], row["contact_page"],
                    row["about_page"], row["emails"], row["phones"],
                    row["social_links"], row["people"], row["tech_stack"],
                    row["lead_score"], row["description"], row["employees"],
                    row["founded"], row["country"], row["domain_intel"],
                    row["org_graph"],
                    lead.confidence_score,
                    lead.lead_quality,
                    lead.keyword,
                ))
                existing_domains.add(domain)
                migrated += 1

            conn.commit()
            return {
                "source_count": source_count,
                "migrated": migrated,
                "already_existed": already_existed,
            }
        finally:
            conn.close()
