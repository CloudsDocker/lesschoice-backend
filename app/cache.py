import time
from threading import Lock
from typing import Any, Optional


class TTLCache:
    """Simple in-process TTL cache. Best-effort only: Cloud Run can run multiple
    instances and restarts drop this, but it still absorbs the bulk of repeat
    lookups for popular places within an instance's lifetime."""

    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.time():
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        with self._lock:
            self._store[key] = (time.time() + ttl_seconds, value)
