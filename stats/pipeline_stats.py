import logging
from typing import Dict, Any
from pillar3.network import signals

logger = logging.getLogger(__name__)

class PipelineStatsTracker:
    """
    Decoupled stats tracker that compiles ETL and Item Pipeline metrics
    by listening to pipeline item signals.
    """
    def __init__(self):
        self.unique_master_records = 0
        self.dropped_validation = 0
        self.dropped_no_domain = 0
        self.duplicates_merged = 0
        self.source_breakdown: Dict[str, int] = {}
        
        signals.connect(self.on_item_scraped, signals.ITEM_SCRAPED)
        signals.connect(self.on_item_dropped, signals.ITEM_DROPPED)

    def on_item_scraped(self, item: dict) -> None:
        self.unique_master_records += 1
        # Extract the source domain if available
        source = item.get("source")
        if source:
            self.source_breakdown[source] = self.source_breakdown.get(source, 0) + 1

    def on_item_dropped(self, item: dict, pipeline: Any, exception: Any = None) -> None:
        pipe_class_name = pipeline.__class__.__name__
        if "Validation" in pipe_class_name:
            self.dropped_validation += 1
        elif "Deduplication" in pipe_class_name:
            self.dropped_no_domain += 1

pipeline_stats = PipelineStatsTracker()
