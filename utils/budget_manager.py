import logging
from utils.deadline import Deadline

logger = logging.getLogger(__name__)

class ProviderBudgetManager:
    """
    ProviderBudgetManager: timing responsibilities removed.
    The single authority for time is the parent Deadline hierarchy.
    No independent wall-clock state, no hardcoded per-provider budgets.
    """
    def __init__(self):
        pass

    def start_provider(self, pname: str):
        """No-op: provider independent clocks have been removed."""
        pass

    def get_provider_budget(self, pname: str, deadline: Deadline | None = None) -> float:
        """Return remaining time on parent deadline or fallback budget."""
        if deadline:
            return deadline.remaining()
        return 8.0

    def can_execute(self, pname: str, deadline: Deadline | None = None) -> bool:
        """
        Check if the provider is allowed to start or continue retrying.
        Returns False only if the deadline is exhausted (<1.0s remaining).
        """
        if deadline and (deadline.is_exceeded() or deadline.remaining() < 1.0):
            logger.warning(f"[ProviderBudgetManager] Blocked '{pname}': deadline exceeded.")
            return False
        return True

    def remaining_provider_time(self, pname: str, deadline: Deadline | None = None) -> float:
        """Return remaining time on parent deadline."""
        return deadline.remaining() if deadline else 999.0

    def get_dynamic_timeout(self, pname: str, default_timeout: float = 8.0, deadline: Deadline | None = None) -> float:
        """Calculate timeout strictly bounded by parent deadline."""
        if deadline:
            return deadline.bounded_timeout(default_timeout)
        return default_timeout
