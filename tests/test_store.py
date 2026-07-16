"""Unit tests for the session/run store, including the Redis-backed path
exercised via `fakeredis` (no real Redis server required)."""

from __future__ import annotations

import fakeredis

from agentops_sentinel.store import SessionStore, build_session_store


class TestInMemoryBackend:
    def test_save_and_get_round_trip(self):
        store = SessionStore()
        assert store.backend == "memory"
        store.save_run("ticket-1", {"status": "completed"})
        assert store.get_run("ticket-1") == {"status": "completed"}

    def test_missing_ticket_returns_none(self):
        store = SessionStore()
        assert store.get_run("nope") is None

    def test_list_ticket_ids(self):
        store = SessionStore()
        store.save_run("a", {})
        store.save_run("b", {})
        assert set(store.list_ticket_ids()) == {"a", "b"}


class TestRedisBackedStore:
    """Uses fakeredis so this exercises the real Redis code path (JSON
    serialize/deserialize, key prefixing) with zero network access and
    no dependency on a running Redis server."""

    def _fake_client(self):
        return fakeredis.FakeStrictRedis()

    def test_save_and_get_round_trip(self):
        store = SessionStore(redis_client=self._fake_client())
        assert store.backend == "redis"
        store.save_run("ticket-42", {"status": "escalated", "cost_used_usd": 0.12})
        assert store.get_run("ticket-42") == {"status": "escalated", "cost_used_usd": 0.12}

    def test_missing_ticket_returns_none(self):
        store = SessionStore(redis_client=self._fake_client())
        assert store.get_run("nope") is None

    def test_list_ticket_ids_strips_key_prefix(self):
        store = SessionStore(redis_client=self._fake_client())
        store.save_run("a", {})
        store.save_run("b", {})
        assert set(store.list_ticket_ids()) == {"a", "b"}


class TestBuildSessionStore:
    def test_empty_url_gives_memory_backend(self):
        store = build_session_store("")
        assert store.backend == "memory"

    def test_unreachable_redis_falls_back_to_memory(self):
        # Port 1 is not a real Redis server; connecting must fail fast
        # (short timeout is set inside build_session_store) and fall
        # back gracefully rather than raising or hanging.
        store = build_session_store("redis://127.0.0.1:1/0")
        assert store.backend == "memory"
