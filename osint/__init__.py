"""
osint/__init__.py
=================
Modular OSINT Provider and Orchestration Architecture for the Flowiz Data Crawling Pipeline.
"""

from .models import ProviderCapability, ProviderResult, ProviderStatus
from .base import BaseOSINTProvider
from .registry import ProviderRegistry
from .orchestrator import OSINTOrchestrator
from .providers import (
    WHOISProvider,
    DNSMXProvider,
    DomainIntelProvider,
    EmailVerificationProvider,
    HunterProvider,
    OpenCorporatesProvider,
    ZaubaRegistryProvider,
    SocialDiscoveryProvider,
    PhoneValidationProvider,
    DeepContactsProvider,
)


def get_default_orchestrator() -> OSINTOrchestrator:
    """
    Factory function initializing an OSINTOrchestrator pre-configured with
    all standard modular providers.
    """
    registry = ProviderRegistry()
    registry.register(DomainIntelProvider())
    registry.register(WHOISProvider())
    registry.register(DNSMXProvider())
    registry.register(EmailVerificationProvider())
    registry.register(HunterProvider())
    registry.register(OpenCorporatesProvider())
    registry.register(ZaubaRegistryProvider())
    registry.register(SocialDiscoveryProvider())
    registry.register(PhoneValidationProvider())
    registry.register(DeepContactsProvider())
    return OSINTOrchestrator(registry=registry)


__all__ = [
    "OSINTOrchestrator",
    "ProviderRegistry",
    "BaseOSINTProvider",
    "ProviderResult",
    "ProviderStatus",
    "ProviderCapability",
    "get_default_orchestrator",
    "WHOISProvider",
    "DNSMXProvider",
    "DomainIntelProvider",
    "EmailVerificationProvider",
    "HunterProvider",
    "OpenCorporatesProvider",
    "ZaubaRegistryProvider",
    "SocialDiscoveryProvider",
    "PhoneValidationProvider",
    "DeepContactsProvider",
]
