import os
import sys
import logging
import pkgutil
import importlib
from typing import Dict, Any, Type, Optional, List

from search.provider_base import SearchProvider

logger = logging.getLogger(__name__)

from search.base_registry import BaseRegistry

# Concrete implementation for ProviderRegistry
class ProviderRegistryClass(BaseRegistry):
    def __init__(self):
        scan_dir = os.path.join(os.path.dirname(__file__), "providers")
        super().__init__(
            base_class=SearchProvider,
            module_prefix="search.providers",
            scan_path=scan_dir
        )

    def get_provider_class(self, name: str) -> Optional[Type]:
        alias_map = {
            "directory": "directory_provider",
            "repository": "repository_provider",
        }
        resolved = alias_map.get(name, name)
        return self.get(resolved)

ProviderRegistry = ProviderRegistryClass()

# Lazy dictionary for backward-compatibility wrapper
class LazyProviderRegistryDict(dict):
    def __getitem__(self, key):
        cls = ProviderRegistry.get_provider_class(key)
        if not cls:
            raise KeyError(key)
        return cls

    def __contains__(self, key):
        return ProviderRegistry.get_provider_class(key) is not None

    def keys(self):
        return ProviderRegistry.get_registered_names()

    def __iter__(self):
        return iter(ProviderRegistry.get_registered_names())

    def items(self):
        return [(name, ProviderRegistry.get_provider_class(name)) for name in ProviderRegistry.get_registered_names()]

PROVIDER_REGISTRY = LazyProviderRegistryDict()

DEFAULT_PRIORITY: list[str] = [
    "google_html",
    "duckduckgo",
    "brave",
    "bing",
    "directory_provider",
    "repository_provider",
]
