"""AgentRunner: the public entry point that runs one ticket end-to-end.

Wires together the LLM client, guardrail ledger, decision-trace store,
and compiled LangGraph workflow, then persists a summary of the run to
the session store so the API/dashboard can retrieve it later.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from agentops_sentinel.config import Settings, get_settings
from agentops_sentinel.graph import GraphRuntime, TicketState, build_graph
from agentops_sentinel.guardrails import GuardrailLedger
from agentops_sentinel.llm import LLMClient, build_llm_client
from agentops_sentinel.store import SessionStore, build_session_store


@dataclass
class RunResult:
    ticket_id: str
    status: str  # "completed" | "escalated"
    final_answer: str | None
    escalation_reason: str | None
    route: str | None
    steps_used: int
    cost_used_usd: float
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "status": self.status,
            "final_answer": self.final_answer,
            "escalation_reason": self.escalation_reason,
            "route": self.route,
            "steps_used": self.steps_used,
            "cost_used_usd": round(self.cost_used_usd, 4),
            "events": self.events,
        }


class AgentRunner:
    """Runs support tickets through the supervisor/sub-agent/critique graph."""

    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._llm_override = llm
        self.session_store = session_store or build_session_store(self.settings.redis_url)

    def _build_llm(self) -> LLMClient:
        return self._llm_override or build_llm_client(self.settings)

    def run(self, ticket_text: str, ticket_id: str | None = None) -> RunResult:
        ticket_id = ticket_id or f"ticket-{uuid.uuid4().hex[:12]}"
        ledger = GuardrailLedger(
            max_steps=self.settings.max_steps, budget_usd=self.settings.budget_usd
        )
        runtime = GraphRuntime(settings=self.settings, llm=self._build_llm(), ledger=ledger)
        app = build_graph(runtime)

        initial_state: TicketState = {
            "ticket_id": ticket_id,
            "ticket_text": ticket_text,
            "status": "running",
            "events": [],
        }
        final_state: TicketState = app.invoke(initial_state, config={"recursion_limit": 50})

        result = RunResult(
            ticket_id=ticket_id,
            status=final_state.get("status", "unknown"),
            final_answer=final_state.get("final_answer"),
            escalation_reason=final_state.get("escalation_reason"),
            route=final_state.get("route"),
            steps_used=ledger.steps_used,
            cost_used_usd=ledger.cost_used_usd,
            events=final_state.get("events", []),
        )
        self.session_store.save_run(ticket_id, result.to_dict())
        return result


def get_default_runner() -> AgentRunner:
    return AgentRunner()
