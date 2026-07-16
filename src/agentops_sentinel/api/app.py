"""FastAPI application exposing ticket submission, run lookup, and traces.

Kept intentionally small and synchronous: ticket runs in this project
are fast, deterministic, in-process graph executions (no real network
calls), so there is no need for a task queue -- `POST /tickets` runs
the graph to completion and returns the result directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agentops_sentinel import tracing
from agentops_sentinel.runner import AgentRunner

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"


class TicketRequest(BaseModel):
    ticket_text: str = Field(..., min_length=1, max_length=4000)
    ticket_id: str | None = None


class TicketResponse(BaseModel):
    ticket_id: str
    status: str
    final_answer: str | None
    escalation_reason: str | None
    route: str | None
    steps_used: int
    cost_used_usd: float
    events: list[dict]


@lru_cache(maxsize=1)
def _get_runner() -> AgentRunner:
    return AgentRunner()


def create_app(runner: AgentRunner | None = None) -> FastAPI:
    """Build the FastAPI app. Pass `runner` explicitly in tests to inject
    a runner wired with fakes/fixtures instead of the process-wide default.
    """
    app = FastAPI(title="agentops-sentinel", version="0.1.0")
    app.state.runner = runner or _get_runner()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/tickets", response_model=TicketResponse)
    def submit_ticket(request: TicketRequest) -> TicketResponse:
        result = app.state.runner.run(request.ticket_text, ticket_id=request.ticket_id)
        return TicketResponse(**result.to_dict())

    @app.get("/tickets/{ticket_id}", response_model=TicketResponse)
    def get_ticket(ticket_id: str) -> TicketResponse:
        summary = app.state.runner.session_store.get_run(ticket_id)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"No run found for ticket '{ticket_id}'")
        return TicketResponse(**summary)

    @app.get("/traces")
    def list_traces() -> dict:
        return {"trace_ids": tracing.decision_store.list_traces()}

    @app.get("/traces/{trace_id}")
    def get_trace(trace_id: str) -> dict:
        spans = tracing.decision_store.get_trace(trace_id)
        if not spans:
            raise HTTPException(status_code=404, detail=f"No trace found for id '{trace_id}'")
        return {"trace_id": trace_id, "spans": spans}

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard() -> str:
        return _DASHBOARD_PATH.read_text(encoding="utf-8")

    return app


app = create_app()
