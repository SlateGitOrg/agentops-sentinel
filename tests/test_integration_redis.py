"""Optional integration test against a REAL Redis server.

Skipped by default -- it only runs if `AGENTOPS_TEST_REDIS_URL` is set
(e.g. by CI running a Redis service container, or a developer with
`docker compose up redis`). The main test suite never depends on this
and passes fully offline via `fakeredis` in `test_store.py`.
"""

from __future__ import annotations

import os

import pytest

from agentops_sentinel.store import build_session_store

pytestmark = pytest.mark.integration

REDIS_URL = os.environ.get("AGENTOPS_TEST_REDIS_URL")


@pytest.mark.skipif(REDIS_URL is None, reason="AGENTOPS_TEST_REDIS_URL not set; skipping real-Redis test")
def test_save_and_get_round_trip_against_real_redis():
    store = build_session_store(REDIS_URL)
    assert store.backend == "redis"
    store.save_run("integration-ticket", {"status": "completed"})
    assert store.get_run("integration-ticket") == {"status": "completed"}
