"""
osint/registry.py
=================
Central registry for discovering, registering, and retrieving OSINT providers.
"""

import logging
from typing import Dict, List, Optional
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """
    Registry for managing available OSINT provider instances.
    """

    def __init__(self):
        self._providers: Dict[str, BaseOSINTProvider] = {}

    def register(self, provider: BaseOSINTProvider) -> None:
        """Register a provider instance."""
        if not isinstance(provider, BaseOSINTProvider):
            raise TypeError(f"Expected BaseOSINTProvider, got {type(provider)}")
        if provider.name in self._providers:
            logger.debug(f"[ProviderRegistry] Overwriting existing provider registration for '{provider.name}'")
        self._providers[provider.name] = provider
        logger.debug(f"[ProviderRegistry] Registered provider: {provider.name} ({provider.capability.value})")

    def unregister(self, name: str) -> Optional[BaseOSINTProvider]:
        """Remove a provider by name."""
        return self._providers.pop(name, None)

    def get(self, name: str) -> Optional[BaseOSINTProvider]:
        """Lookup provider by unique name."""
        return self._providers.get(name)

    def get_by_capability(self, capability: ProviderCapability) -> List[BaseOSINTProvider]:
        """Get all providers matching a given capability."""
        return [p for p in self._providers.values() if p.capability == capability]

    def list_providers(self) -> List[str]:
        """Return names of all registered providers."""
        return list(self._providers.keys())

    def get_all(self) -> List[BaseOSINTProvider]:
        """Return all registered provider instances."""
        return list(self._providers.values())

    def clear(self) -> None:
        """Clear all registered providers."""
        self._providers.clear()
