"""Shared pytest fixtures.

Every test gets a fresh OpenTelemetry tracer provider and decision
trace store so traces from one test never leak into another (spans
are exported synchronously via SimpleSpanProcessor, so there is no
async flush to worry about).
"""

from __future__ import annotations

import pytest

from agentops_sentinel.tracing import DecisionTraceStore, configure_tracing


@pytest.fixture(autouse=True)
def isolated_tracing():
    store = DecisionTraceStore()
    configure_tracing(service_name="agentops-sentinel-test", store=store)
    yield store
    store.clear()
