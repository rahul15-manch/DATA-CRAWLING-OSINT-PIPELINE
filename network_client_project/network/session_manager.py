from curl_cffi import requests
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class SessionFactory:
    """
    Creates and manages pre-configured, highly optimized requests.Session objects
    using curl_cffi for browser TLS fingerprinting.
    """
    
    @staticmethod
    def create_session(provider: Optional[str] = None, domain: Optional[str] = None) -> requests.Session:
        """
        Creates a session configured to impersonate a modern Chrome browser.
        The session keeps lightweight provider/domain metadata so requests can be
        isolated and reused more realistically across providers.
        """
        session = requests.Session(impersonate="chrome124")
        session._browser_profile = {
            "provider": (provider or "default").lower(),
            "domain": (domain or "generic").lower(),
        }
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

    def get_or_create_session(self, session_id: Optional[str] = None, provider: Optional[str] = None, domain: Optional[str] = None) -> requests.Session:
        """
        Retrieves an existing session or creates a new one.
        If session_id is None, returns an ephemeral session.
        """
        if session_id is None:
            logger.debug("Creating new ephemeral session (no session_id provided)")
            return SessionFactory.create_session(provider=provider, domain=domain)
            
        if session_id not in self._sessions:
            logger.debug(f"Creating new isolated session for ID: {session_id}")
            self._sessions[session_id] = SessionFactory.create_session(provider=provider, domain=domain)
        
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
