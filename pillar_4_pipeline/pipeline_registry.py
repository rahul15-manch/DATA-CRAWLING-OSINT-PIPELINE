import logging
from typing import List, Callable, Optional, Any
from pillar3.network import signals

logger = logging.getLogger(__name__)

class ItemPipelineRegistry:
    """
    Manages a sequence of processing pipeline stages for scraped items.
    Aligns with Scrapy's Item Pipeline pattern.
    """
    def __init__(self):
        self.pipelines: List[Callable[[dict], Optional[dict]]] = []

    def register(self, pipeline: Callable[[dict], Optional[dict]]) -> None:
        """Register a pipeline stage (either class instance or function)."""
        self.pipelines.append(pipeline)
        logger.debug(f"Registered item pipeline stage: {pipeline}")

    def process_item(self, item: dict) -> Optional[dict]:
        """
        Processes an item through all registered pipelines sequentially.
        If any stage returns None, the item is dropped and signals are triggered.
        """
        current_item = item
        for pipe in self.pipelines:
            try:
                res = pipe(current_item)
                if res is None:
                    signals.send(signals.ITEM_DROPPED, item=item, pipeline=pipe)
                    return None
                current_item = res
            except Exception as e:
                logger.error(f"Exception raised in pipeline stage {pipe}: {e}", exc_info=True)
                signals.send(signals.ITEM_DROPPED, item=item, pipeline=pipe, exception=e)
                return None
        
        # Item successfully finished the pipeline
        signals.send(signals.ITEM_SCRAPED, item=current_item)
        return current_item
