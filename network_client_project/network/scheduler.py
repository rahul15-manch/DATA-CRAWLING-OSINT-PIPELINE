import hashlib
import heapq
import time
import logging
from typing import Optional, List, Set, Tuple, Any
from .middleware.base import Request

logger = logging.getLogger(__name__)

class RequestFingerprinter:
    """Generates unique fingerprints for Requests to prevent duplicates."""
    @staticmethod
    def get_fingerprint(request: Request) -> str:
        # Create a stable representation of the request
        query_part = request.query or ""
        provider_part = request.provider or ""
        url_part = request.url.strip().lower()
        method_part = request.method.upper()
        
        raw_string = f"{method_part}:{url_part}:{query_part}:{provider_part}"
        return hashlib.sha1(raw_string.encode('utf-8')).hexdigest()

class Scheduler:
    """
    Scrapy-like Scheduler that manages request queueing,
    prioritization via a min-heap (simulating max-heap), and deduplication.
    """
    def __init__(self):
        self.heap: List[Tuple[Tuple[int, int, float, int], Request]] = []
        self.seen_fingerprints: Set[str] = set()
        self._request_counter = 0

    def enqueue(self, request: Request) -> bool:
        """
        Pushes request to scheduler heap if it has not been processed yet.
        Returns True if enqueued, False if deduplicated.
        """
        fp = RequestFingerprinter.get_fingerprint(request)
        if fp in self.seen_fingerprints:
            logger.debug(f"[Scheduler] Request deduplicated: {request.url} (query={request.query})")
            return False

        self.seen_fingerprints.add(fp)
        self._request_counter += 1
        
        # Priority mapping: heapq is a min-heap, so we negate priority to pop highest first.
        # Priority -> Depth -> Timestamp -> Counter
        priority_tuple = (-request.priority, request.depth, request.timestamp, self._request_counter)
        
        heapq.heappush(self.heap, (priority_tuple, request))
        logger.debug(f"[Scheduler] Enqueued request id={request.id}: {request.url} (priority={request.priority}, depth={request.depth})")
        return True

    def update_priorities(self, source_priorities: dict[str, int]) -> None:
        """Re-prioritize all enqueued requests based on dynamic source weights and re-heapify."""
        new_heap = []
        for priority_tuple, request in self.heap:
            pname = request.provider
            if pname in source_priorities:
                request.priority = source_priorities[pname]
            # Recompute priority tuple
            new_tuple = (-request.priority, request.depth, request.timestamp, priority_tuple[3])
            new_heap.append((new_tuple, request))
        self.heap = new_heap
        heapq.heapify(self.heap)
        logger.debug(f"[Scheduler] Re-prioritized heap based on dynamic source priorities.")

    def next(self) -> Optional[Request]:
        """Pops and returns the highest priority Request from the scheduler."""
        if not self.heap:
            return None
        _, request = heapq.heappop(self.heap)
        return request

    def is_empty(self) -> bool:
        """Return True if heap contains no requests."""
        return len(self.heap) == 0

    def inspect_queue(self) -> List[Request]:
        """Return a copy of the list of all queued Request instances in heap order."""
        sorted_heap = sorted(self.heap, key=lambda x: x[0])
        return [req for _, req in sorted_heap]

    def remove_request(self, request_id: str) -> bool:
        """Remove a request from the heap by its unique id."""
        for i, (_, req) in enumerate(self.heap):
            if req.id == request_id:
                self.heap.pop(i)
                heapq.heapify(self.heap)
                return True
        return False
