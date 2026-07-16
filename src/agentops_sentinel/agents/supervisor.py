"""Supervisor/planner agent: routes a ticket to a specialized sub-agent."""

from __future__ import annotations

from dataclasses import dataclass

from agentops_sentinel.llm import LLMClient

ROUTES = ["kb_agent", "order_agent", "refund_agent", "escalate"]

_SYSTEM_PROMPT = (
    "You are the supervisor of a support-ticket triage system. Given a "
    "customer ticket, route it to exactly one specialist: 'kb_agent' for "
    "how-to/documentation questions, 'order_agent' for shipping/order-status "
    "questions, 'refund_agent' for refund/cancellation requests, or "
    "'escalate' if the customer is hostile, mentions legal action/fraud, or "
    "the request is ambiguous and needs a human."
)


@dataclass
class SupervisorDecision:
    route: str
    confidence: float
    rationale: str


def run_supervisor(ticket_text: str, llm: LLMClient) -> SupervisorDecision:
    decision = llm.decide(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=f"Ticket: {ticket_text}",
        choices=ROUTES,
    )
    return SupervisorDecision(
        route=decision.choice, confidence=decision.confidence, rationale=decision.rationale
    )
