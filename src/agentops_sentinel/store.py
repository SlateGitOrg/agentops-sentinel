"""Session/run store: persists ticket-run summaries.

Backed by Redis when a `redis_url` is configured (and reachable),
falling back transparently to an in-memory dict otherwise -- this
keeps the default, test-time path fully offline while still letting
the same code run against a real Redis in production or CI-with-a
-service-container. Tests that want to exercise the Redis code path
without a real server inject a `fakeredis` client directly.
"""

from __future__ import annotations

import json
from typing import Any, Protocol


class _RedisLike(Protocol):
    def set(self, name: str, value: str) -> Any: ...
    def get(self, name: str) -> Any: ...
    def keys(self, pattern: str) -> Any: ...


class SessionStore:
    """Stores JSON-serializable run summaries keyed by ticket id."""

    _KEY_PREFIX = "agentops:run:"

    def __init__(self, redis_client: _RedisLike | None = None) -> None:
        self._redis = redis_client
        self._memory: dict[str, dict] = {}

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    def _key(self, ticket_id: str) -> str:
        return f"{self._KEY_PREFIX}{ticket_id}"

    def save_run(self, ticket_id: str, summary: dict) -> None:
        if self._redis is not None:
            self._redis.set(self._key(ticket_id), json.dumps(summary))
        else:
            self._memory[ticket_id] = summary

    def get_run(self, ticket_id: str) -> dict | None:
        if self._redis is not None:
            raw = self._redis.get(self._key(ticket_id))
            if raw is None:
                return None
            return json.loads(raw)
        return self._memory.get(ticket_id)

    def list_ticket_ids(self) -> list[str]:
        if self._redis is not None:
            keys = self._redis.keys(f"{self._KEY_PREFIX}*")
            return [
                (k.decode() if isinstance(k, (bytes, bytearray)) else k)[len(self._KEY_PREFIX) :]
                for k in keys
            ]
        return list(self._memory.keys())


def build_session_store(redis_url: str = "") -> SessionStore:
    """Build a SessionStore, trying Redis only if a URL was configured.

    Any connectivity problem falls back to the in-memory backend rather
    than raising -- an unreachable Redis should degrade the system, not
    crash it, and it must never be *required* for the offline test
    suite to pass.
    """
    if not redis_url:
        return SessionStore(redis_client=None)
    try:
        import redis as redis_lib

        client = redis_lib.from_url(redis_url, socket_connect_timeout=0.5)
        client.ping()
        return SessionStore(redis_client=client)
    except Exception:
        return SessionStore(redis_client=None)
