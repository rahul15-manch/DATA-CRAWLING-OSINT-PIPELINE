import threading
import logging
from typing import Callable, Dict, List, Any

logger = logging.getLogger(__name__)

# Standard signal names used throughout the pipeline
REQUEST_RECEIVED = "request_received"
REQUEST_COMPLETED = "request_completed"
REQUEST_FAILED = "request_failed"
ITEM_SCRAPED = "item_scraped"
ITEM_DROPPED = "item_dropped"

_receivers: Dict[str, List[Callable]] = {}
_lock = threading.Lock()

def connect(receiver: Callable, event: str) -> None:
    """Register a callback function to listen for a specific event signal."""
    if not callable(receiver):
        raise ValueError("Receiver must be a callable function or method.")
    
    with _lock:
        if event not in _receivers:
            _receivers[event] = []
        if receiver not in _receivers[event]:
            _receivers[event].append(receiver)
            logger.debug(f"Connected receiver {receiver.__name__ if hasattr(receiver, '__name__') else receiver} to signal '{event}'")

def disconnect(receiver: Callable, event: str) -> None:
    """Disconnect a callback function from a specific event signal."""
    with _lock:
        if event in _receivers and receiver in _receivers[event]:
            _receivers[event].remove(receiver)
            logger.debug(f"Disconnected receiver {receiver.__name__ if hasattr(receiver, '__name__') else receiver} from signal '{event}'")

def send(event: str, **kwargs: Any) -> None:
    """Emit an event signal, invoking all connected receivers with the provided keyword arguments."""
    with _lock:
        callbacks = list(_receivers.get(event, []))
        
    for callback in callbacks:
        try:
            callback(**kwargs)
        except Exception as e:
            logger.error(f"Error in signal receiver {callback} for event '{event}': {e}", exc_info=True)

# Auto-wire stats observers on import
try:
    import stats.provider_stats
    import stats.proxy_stats
except ImportError:
    pass
