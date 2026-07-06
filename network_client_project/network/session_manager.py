import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class SessionFactory:
    """
    Creates and manages pre-configured, highly optimized requests.Session objects.
    """
    
    @staticmethod
    def create_session(
        pool_connections: int = 100, 
        pool_maxsize: int = 100, 
        max_retries: int = 0
    ) -> requests.Session:
        """
        Creates a session with customized connection pooling.
        Note: We keep max_retries at 0 by default here because we will build
        a much smarter, application-level Retry Engine in the next module.
        """
        session = requests.Session()
        
        # Configure urllib3 connection pooling
        # This allows the session to keep `pool_maxsize` TCP connections alive in memory.
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=max_retries
        )
        
        # Mount the adapter for both HTTP and HTTPS protocols
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session

class SessionManager:
    """
    Manages isolated sessions for different crawler tasks.
    Ensures that cookies from Task A do not leak into Task B.
    """
    def __init__(self):
        self._sessions: Dict[str, requests.Session] = {}
        # We don't necessarily need a strict lock here if sessions are created per-thread,
        # but in a shared context, you'd want to manage state carefully.

    def get_or_create_session(self, session_id: str) -> requests.Session:
        """
        Retrieves an existing session or creates a new one.
        This is how we maintain state (Cookies) across multiple requests for a single crawler target.
        """
        if session_id not in self._sessions:
            logger.debug(f"Creating new isolated session for ID: {session_id}")
            self._sessions[session_id] = SessionFactory.create_session()
        
        return self._sessions[session_id]

    def clear_session(self, session_id: str):
        """
        Destroys a session, wiping its cookies and closing its TCP connections.
        Mandatory to prevent memory leaks in long-running pipelines.
        """
        if session_id in self._sessions:
            session = self._sessions.pop(session_id)
            session.close()  # Gracefully close underlying TCP connections
            logger.debug(f"Cleared session and closed connections for ID: {session_id}")
            
    def clear_all(self):
        """Shutdown all sessions gracefully."""
        for session_id in list(self._sessions.keys()):
            self.clear_session(session_id)
