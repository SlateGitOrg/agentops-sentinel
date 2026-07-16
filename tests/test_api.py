"""Integration tests for the FastAPI surface (in-process, no real network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentops_sentinel.api.app import create_app
from agentops_sentinel.config import Settings
from agentops_sentinel.runner import AgentRunner


@pytest.fixture
def client() -> TestClient:
    app = create_app(runner=AgentRunner(settings=Settings.load()))
    return TestClient(app)


class TestHealth:
    def test_health_check(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestSubmitTicket:
    def test_submit_kb_ticket_returns_completed_result(self, client: TestClient):
        response = client.post(
            "/tickets", json={"ticket_text": "How do I reset my password?", "ticket_id": "api-kb-1"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ticket_id"] == "api-kb-1"
        assert body["status"] == "completed"
        assert body["route"] == "kb_agent"

    def test_submit_without_explicit_id_generates_one(self, client: TestClient):
        response = client.post("/tickets", json={"ticket_text": "How do I reset my password?"})
        assert response.status_code == 200
        assert response.json()["ticket_id"].startswith("ticket-")

    def test_empty_ticket_text_is_rejected(self, client: TestClient):
        response = client.post("/tickets", json={"ticket_text": ""})
        assert response.status_code == 422


class TestGetTicket:
    def test_get_existing_ticket(self, client: TestClient):
        client.post("/tickets", json={"ticket_text": "Where is order ORD-1001?", "ticket_id": "api-get-1"})
        response = client.get("/tickets/api-get-1")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    def test_get_missing_ticket_returns_404(self, client: TestClient):
        response = client.get("/tickets/does-not-exist")
        assert response.status_code == 404


class TestTraces:
    def test_traces_are_recorded_and_retrievable(self, client: TestClient):
        client.post(
            "/tickets", json={"ticket_text": "How do I configure SSO?", "ticket_id": "api-trace-1"}
        )
        list_response = client.get("/traces")
        assert list_response.status_code == 200
        assert "api-trace-1" in list_response.json()["trace_ids"]

        trace_response = client.get("/traces/api-trace-1")
        assert trace_response.status_code == 200
        spans = trace_response.json()["spans"]
        assert len(spans) > 0
        assert any(s["name"] == "supervisor.route" for s in spans)

    def test_missing_trace_returns_404(self, client: TestClient):
        response = client.get("/traces/does-not-exist")
        assert response.status_code == 404


class TestDashboard:
    def test_dashboard_serves_html(self, client: TestClient):
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "decision trace dashboard" in response.text.lower()
