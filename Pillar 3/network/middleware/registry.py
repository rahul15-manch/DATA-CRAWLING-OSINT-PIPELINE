import os
import sys
import logging
from search.base_registry import BaseRegistry
from .base import BaseMiddleware

logger = logging.getLogger(__name__)

class MiddlewareRegistryClass(BaseRegistry):
    def __init__(self):
        scan_dir = os.path.dirname(__file__)
        super().__init__(
            base_class=BaseMiddleware,
            module_prefix="network_client_project.network.middleware",
            scan_path=scan_dir
        )

    def get_ordered_middlewares(self) -> list:
        """Returns instantiated middleware instances sorted by their priority attribute."""
        classes = list(self.get_all().values())
        # Sort classes by priority attribute, defaulting to 1000 if not defined
        sorted_classes = sorted(classes, key=lambda cls: getattr(cls, "priority", 1000))
        instances = []
        for cls in sorted_classes:
            try:
                instances.append(cls())
                logger.debug(f"[MiddlewareRegistry] Instantiated and added: {cls.__name__} (priority={getattr(cls, 'priority', 1000)})")
            except Exception as e:
                logger.error(f"Failed to instantiate middleware {cls}: {e}", exc_info=True)
        return instances

MiddlewareRegistry = MiddlewareRegistryClass()
