import sqlite3
import json
import logging
from ..exporters import BaseExporter

logger = logging.getLogger(__name__)

class SQLiteExporter(BaseExporter):
    """Exporter that writes cleaned lead items to SQLite database."""
    name = "sqlite"

    def __init__(self, db_path: str = "leads.db"):
        self.db_path = db_path

    def export(self, items: list) -> None:
        if not items:
            logger.info("[SQLiteExporter] No items to export.")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Initialize schema
        from ..export import setup_database
        setup_database(cursor)

        success_count = 0
        for record in items:
            try:
                emails = json.dumps(record.get('emails', []))
                phones = json.dumps(record.get('phones', []))
                social_links = json.dumps(record.get('social_links', {}))
                people = json.dumps(record.get('people', []))
                tech_stack = json.dumps(record.get('tech_stack', []))
                domain_intel = json.dumps(record.get('domain_intel') or {})
                org_graph = json.dumps(record.get('org_graph') or {})

                cursor.execute('''
                    INSERT OR REPLACE INTO flowiz_leads (
                        domain, company_name, website, industry, location, 
                        contact_page, about_page, emails, phones, social_links, people,
                        tech_stack, lead_score, description, employees, founded, country,
                        domain_intel, org_graph
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    record.get('domain'),
                    record.get('company_name'),
                    record.get('website'),
                    record.get('industry'),
                    record.get('location'),
                    record.get('contact_page'),
                    record.get('about_page'),
                    emails,
                    phones,
                    social_links,
                    people,
                    tech_stack,
                    record.get('lead_score'),
                    record.get('description'),
                    record.get('employees'),
                    record.get('founded'),
                    record.get('country'),
                    domain_intel,
                    org_graph
                ))
                success_count += 1
            except Exception as e:
                logger.error(f"[SQLiteExporter] Failed to insert record for {record.get('domain')}: {e}")

        conn.commit()
        conn.close()
        logger.info(f"[SQLiteExporter] Successfully exported {success_count} records to SQLite database: {self.db_path}")
