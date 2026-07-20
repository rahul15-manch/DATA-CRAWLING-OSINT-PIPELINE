import json
import logging
from ..exporters import BaseExporter

logger = logging.getLogger(__name__)

class JsonExporter(BaseExporter):
    """Exporter that writes cleaned lead items to a JSON file."""
    name = "json"

    def __init__(self, filepath: str = "cleaned_data.json"):
        self.filepath = filepath

    def export(self, items: list) -> None:
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(items, f, indent=2, ensure_ascii=False)
            logger.info(f"[JsonExporter] Successfully exported {len(items)} records to JSON file: {self.filepath}")
        except Exception as e:
            logger.error(f"[JsonExporter] Failed to write JSON file: {e}")
