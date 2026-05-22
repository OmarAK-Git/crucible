"""
In-memory session store for Crucible.

NOTE: This is a temporary, in-memory dictionary-based store guarded by a threading.Lock.
It is for Phase 1 & 2; SQLite-based persistence will land in Phase 3.
"""
import threading
from typing import Optional, Dict, Any

_lock = threading.Lock()
_sessions: Dict[str, Dict[str, Any]] = {}

def store_session(
    session_id: str,
    prompt: str,
    defender_response: Dict[str, Any],
    challenger_response: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Stores a session with both adversary responses. Returns the stored session dictionary.
    """
    with _lock:
        session_data = {
            "session_id": session_id,
            "prompt": prompt,
            "defender_response": defender_response,
            "challenger_response": challenger_response
        }
        _sessions[session_id] = session_data
        return session_data

def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves a session by ID. Returns None if not found.
    """
    with _lock:
        return _sessions.get(session_id)
