import time

class Deadline:
    """
    Global thread-safe deadline tracker to enforce pipeline-level and request-level timeouts.
    """
    _deadline = None

    @classmethod
    def set_timeout(cls, duration_seconds: float):
        cls._deadline = time.time() + duration_seconds

    @classmethod
    def is_exceeded(cls) -> bool:
        if cls._deadline is None:
            return False
        return time.time() > cls._deadline

    @classmethod
    def remaining(cls) -> float:
        if cls._deadline is None:
            return 999.0
        return max(0.0, cls._deadline - time.time())
