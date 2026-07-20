import os
import sys
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from search.base_registry import BaseRegistry
from network_client_project.network import signals

logger = logging.getLogger(__name__)

class BaseExporter(ABC):
    """Abstract base class that all data exporters must implement."""
    @abstractmethod
    def export(self, items: List[Dict[str, Any]]) -> None:
        """Export list of items."""
        pass

class ExporterRegistryClass(BaseRegistry):
    def __init__(self):
        scan_dir = os.path.dirname(__file__)
        super().__init__(
            base_class=BaseExporter,
            module_prefix="pillar_4_pipeline.exporters",
            scan_path=scan_dir
        )

    def get_exporter(self, name: str, **kwargs) -> Optional[BaseExporter]:
        cls = self.get(name)
        if cls:
            return cls(**kwargs)
        return None

ExporterRegistry = ExporterRegistryClass()

class ItemCollector:
    """
    Subscribes to signal item_scraped and accumulates processed items.
    At close(), dispatches accumulated items to registered exporters.
    """
    def __init__(self):
        self.items: List[Dict[str, Any]] = []
        self.exporters: List[BaseExporter] = []
        signals.connect(self.on_item_scraped, signals.ITEM_SCRAPED)

    def register_exporter(self, exporter: BaseExporter) -> None:
        self.exporters.append(exporter)

    def on_item_scraped(self, item: Dict[str, Any]) -> None:
        self.items.append(item)

    def close(self) -> None:
        """Triggers batch export to all registered exporters."""
        for exporter in self.exporters:
            try:
                exporter.export(self.items)
            except Exception as e:
                logger.error(f"Error in exporter {exporter}: {e}", exc_info=True)
