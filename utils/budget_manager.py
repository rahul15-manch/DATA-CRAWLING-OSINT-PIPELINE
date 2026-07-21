import time
import logging
from utils.deadline import Deadline
import config

logger = logging.getLogger(__name__)

class ProviderBudgetManager:
    """
    Centralized Provider Budget Manager responsible for:
    - Allocating time budgets per search provider.
    - Tracking active provider elapsed time.
    - Enforcing budget caps and deadline checks.
    - Ensuring no provider starves fallback providers.
    """
    def __init__(self):
        # Default budgets matching user preferences: Google (8s), DDG/Brave/Bing (7s)
        self.provider_budgets = getattr(config, "PROVIDER_EXECUTION_BUDGETS", {
            "google_html": 8.0,
            "duckduckgo": 7.0,
            "brave": 7.0,
            "bing": 7.0,
        })
        self.active_provider = None
        self.active_provider_start = None

    def start_provider(self, pname: str):
        """Set the active provider and mark the start time."""
        self.active_provider = pname
        self.active_provider_start = time.time()
        logger.info(f"[ProviderBudgetManager] Starting provider '{pname}' with budget limit of {self.get_provider_budget(pname):.1f}s.")

    def get_provider_budget(self, pname: str) -> float:
        """Return the maximum allowed time budget for a provider."""
        if pname == "brightdata":
            # BrightData budget should be dynamic: max(remaining_budget, 5s)
            return max(Deadline.remaining(), 5.0)
        return self.provider_budgets.get(pname, 15.0)

    def remaining_provider_time(self, pname: str) -> float:
        """Calculate the remaining budget for the active provider."""
        budget = self.get_provider_budget(pname)
        if self.active_provider != pname or self.active_provider_start is None:
            return budget
        
        elapsed = time.time() - self.active_provider_start
        return max(0.0, budget - elapsed)

    def can_execute(self, pname: str) -> bool:
        """
        Check if the provider is allowed to start or continue retrying.
        Returns False if the global deadline or provider budget is exhausted.
        """
        # 1. Check global deadline
        if Deadline.is_exceeded():
            logger.warning(f"[ProviderBudgetManager] Blocked '{pname}': global deadline exceeded.")
            return False

        # 2. Check provider-specific execution budget
        if self.active_provider == pname and self.active_provider_start is not None:
            elapsed = time.time() - self.active_provider_start
            budget = self.get_provider_budget(pname)
            if elapsed >= budget:
                logger.warning(
                    f"[ProviderBudgetManager] Blocked '{pname}': provider execution budget exhausted "
                    f"({elapsed:.1f}s elapsed, limit was {budget:.1f}s)."
                )
                return False

        # 3. Check Google low-budget fallback constraint
        if pname == "google_html":
            min_fallback = getattr(config, "GOOGLE_MIN_FALLBACK_BUDGET", 18.0)
            remaining_global = Deadline.remaining()
            if remaining_global < min_fallback:
                logger.warning(
                    f"[ProviderBudgetManager] Blocked Google Search: remaining budget too low ({remaining_global:.1f}s remaining), "
                    f"minimum required fallback budget is {min_fallback:.1f}s."
                )
                return False

        return True
