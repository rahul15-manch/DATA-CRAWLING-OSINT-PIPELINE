"""
osint/base.py
=============
Base class and interface contract for all OSINT providers.
Guarantees isolated execution, bounded timeouts, and consistent ProviderResult returns.
"""

import abc
import asyncio
import logging
import time
from typing import Any, Dict, Optional, Union

from models.lead_record import LeadRecord
from osint.models import ProviderCapability, ProviderResult, ProviderStatus

logger = logging.getLogger(__name__)


class BaseOSINTProvider(abc.ABC):
    """
    Abstract base class for all OSINT intelligence providers.
    """

    name: str = "base_provider"
    capability: ProviderCapability = ProviderCapability.CUSTOM
    critical: bool = False
    default_timeout: float = 5.0

    def __init__(self, timeout: Optional[float] = None, **kwargs: Any):
        self.timeout = timeout if timeout is not None else self.default_timeout
        self.config = kwargs

    @abc.abstractmethod
    async def enrich(self, lead: LeadRecord) -> ProviderResult:
        """
        Subclasses implement provider-specific extraction and evidence collection.
        Should return a ProviderResult.
        """
        raise NotImplementedError

    async def run_safe(self, lead: LeadRecord) -> ProviderResult:
        """
        Executes the provider with bounded timeout and top-level failure isolation.
        Catches any unexpected errors or timeouts and returns a structured ProviderResult.
        """
        start_t = time.perf_counter()
        try:
            result = await asyncio.wait_for(self.enrich(lead), timeout=self.timeout)
            result.execution_time_ms = round((time.perf_counter() - start_t) * 1000, 2)
            return result
        except asyncio.TimeoutError:
            duration_ms = round((time.perf_counter() - start_t) * 1000, 2)
            logger.warning(f"[{self.name}] Provider timed out after {self.timeout}s")
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.TIMEOUT,
                error=f"Operation timed out after {self.timeout} seconds",
                execution_time_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_t) * 1000, 2)
            logger.error(f"[{self.name}] Provider failed with exception: {exc}")
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.ERROR,
                error=f"{type(exc).__name__}: {str(exc)}",
                execution_time_ms=duration_ms,
            )
