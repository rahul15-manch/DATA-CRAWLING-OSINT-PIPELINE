import logging
from ..exporters import BaseExporter
from database.repository import LeadRepository

logger = logging.getLogger(__name__)

class SQLiteExporter(BaseExporter):
    """Exporter that writes cleaned lead items to SQLite database via LeadRepository."""
    name = "sqlite"

    def __init__(self, db_path: str = "leads.db"):
        self.db_path = db_path
        self.repo = LeadRepository(self.db_path)

    def export(self, items: list) -> None:
        if not items:
            logger.info("[SQLiteExporter] No items to export.")
            return

        success_count = self.repo.bulk_upsert_leads(items)
        logger.info(f"[SQLiteExporter] Successfully exported {success_count} records to SQLite database: {self.db_path}")

