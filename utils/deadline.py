import time


class DeadlineExceeded(Exception):
    """Raised when an operation's allocated deadline budget has expired or is insufficient (<1.0s)."""
    pass


class Deadline:
    """
    Instance-based monotonic deadline tracker for request-level, phase-level, and operation timeouts.

    Uses `time.monotonic()` to ensure immunity against system clock adjustments.

    Usage:
        run_deadline = Deadline(100.0)
        discovery_deadline = run_deadline.child(40.0)
        company_deadline = run_deadline.child(15.0)

        run_deadline.require(1.0) # raises DeadlineExceeded if < 1.0s left
        timeout = company_deadline.bounded_timeout(8.0) # raises DeadlineExceeded if < 1.0s left
    """

    def __init__(self, seconds: float):
        """Create a new deadline that expires *seconds* from now."""
        self._expires_at: float = time.monotonic() + max(0.0, float(seconds))

    @classmethod
    def from_expiry(cls, expires_at: float) -> "Deadline":
        """Construct a Deadline directly from an absolute monotonic expiry timestamp."""
        d = cls.__new__(cls)
        d._expires_at = float(expires_at)
        return d

    def child(self, max_seconds: float) -> "Deadline":
        """
        Derive a sub-deadline whose expiry is bounded by the parent's absolute expiry.
        Calculated as min(parent_expires_at, now + max_seconds).
        """
        child_expires = min(self._expires_at, time.monotonic() + max(0.0, float(max_seconds)))
        return Deadline.from_expiry(child_expires)

    def remaining(self) -> float:
        """Seconds remaining until this deadline; 0.0 once exceeded."""
        return max(0.0, self._expires_at - time.monotonic())

    def is_exceeded(self) -> bool:
        """Return True if this deadline has passed (remaining <= 0.0)."""
        return self.remaining() <= 0.0

    def require(self, min_seconds: float = 1.0) -> float:
        """
        Enforce the min_seconds invariant (default 1.0s).
        Raises DeadlineExceeded if remaining time is less than min_seconds.
        Returns the remaining seconds if valid.
        """
        rem = self.remaining()
        if rem < float(min_seconds):
            raise DeadlineExceeded(f"Deadline budget exhausted ({rem:.2f}s remaining < {min_seconds:.2f}s required)")
        return rem

    def bounded_timeout(self, default_seconds: float) -> float:
        """
        Return an operation timeout parameter bounded strictly by remaining deadline time.
        Enforces require(1.0) — raises DeadlineExceeded if remaining time is < 1.0s.
        Otherwise returns min(default_seconds, remaining).
        """
        rem = self.require(1.0)
        return min(float(default_seconds), rem)

    # Aliases for convenience
    def exceeded(self) -> bool:
        return self.is_exceeded()

    def secs_left(self) -> float:
        return self.remaining()
