"""The LangGraph workflow: supervisor -> sub-agent -> self-critique loop.

    START
      |
      v
  supervisor  --(route)-->  kb_agent / order_agent / refund_agent  --(escalate route)--> escalate --> END
      |                              |
      |                              v
      |                          critique
      |                        /    |     \\
      |                    retry  accept  escalate
      |                     |        |        |
      |                     v        v        v
      +---------------(same sub-agent)  respond   escalate
                                          |          |
                                         END        END

Every node is wrapped so that a tripped guardrail (budget, step count,
or per-step timeout) short-circuits straight to the escalate node
instead of raising out of the graph -- guardrail trips are a normal,
traced outcome, not a crash.
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from agentops_sentinel.agents.base import AgentResult
from agentops_sentinel.agents.critique import CritiqueDecision, run_critique
from agentops_sentinel.agents.kb_agent import KnowledgeBaseAgent
from agentops_sentinel.agents.order_agent import OrderAgent
from agentops_sentinel.agents.refund_agent import RefundAgent
from agentops_sentinel.agents.supervisor import SupervisorDecision, run_supervisor
from agentops_sentinel.config import Settings
from agentops_sentinel.guardrails import GuardrailLedger, GuardrailTripped, run_with_timeout
from agentops_sentinel.llm import LLMClient
from agentops_sentinel.tracing import traced_step

SUB_AGENT_ROUTES = ("kb_agent", "order_agent", "refund_agent")


class TicketState(TypedDict, total=False):
    ticket_id: str
    ticket_text: str
    route: str
    attempt: int
    last_result: dict[str, Any]
    critique: dict[str, Any]
    status: str  # "running" | "completed" | "escalated"
    final_answer: str
    escalation_reason: str
    events: list[dict[str, Any]]
    guardrail_tripped: bool


def _log(state: TicketState, **event: Any) -> list[dict[str, Any]]:
    events = list(state.get("events", []))
    events.append(event)
    return events


class GraphRuntime:
    """Bundles the (mutable, per-run) pieces every node needs.

    Kept out of `TicketState` because it holds live objects (an LLM
    client, tool instances, the guardrail ledger) rather than
    JSON-serializable data.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMClient,
        ledger: GuardrailLedger,
        kb_agent: KnowledgeBaseAgent | None = None,
        order_agent: OrderAgent | None = None,
        refund_agent: RefundAgent | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.ledger = ledger
        self.kb_agent = kb_agent or KnowledgeBaseAgent()
        self.order_agent = order_agent or OrderAgent()
        self.refund_agent = refund_agent or RefundAgent()

    def agent_for(self, route: str):
        return {
            "kb_agent": self.kb_agent,
            "order_agent": self.order_agent,
            "refund_agent": self.refund_agent,
        }[route]


def _guarded(
    runtime: GraphRuntime, state: TicketState, step_name: str, fn: Callable[[], TicketState]
) -> TicketState:
    """Run `fn` under the timeout guard, converting any guardrail trip
    into a terminal 'escalated' state update instead of an exception.
    """
    try:
        return run_with_timeout(fn, runtime.settings.step_timeout_s, step_name=step_name)
    except GuardrailTripped as exc:
        return {
            "status": "escalated",
            "escalation_reason": f"guardrail:{type(exc).__name__}: {exc}",
            "guardrail_tripped": True,
            "events": _log(state, node=step_name, guardrail=type(exc).__name__, error=str(exc)),
        }


def build_graph(runtime: GraphRuntime):
    ledger = runtime.ledger

    def supervisor_node(state: TicketState) -> TicketState:
        def _work() -> TicketState:
            ledger.take_step()
            with traced_step(
                "supervisor.route", kind="supervisor", trace_id=state["ticket_id"]
            ) as span:
                decision: SupervisorDecision = run_supervisor(state["ticket_text"], runtime.llm)
                ledger.charge(runtime.settings.cost_per_llm_call, reason="supervisor_llm_call")
                span.set_attribute("agentops.route", decision.route)
                span.set_attribute("agentops.confidence", decision.confidence)
                span.set_attribute("agentops.rationale", decision.rationale)
            return {
                "route": decision.route,
                "attempt": 1,
                "events": _log(
                    state,
                    node="supervisor",
                    route=decision.route,
                    confidence=decision.confidence,
                    rationale=decision.rationale,
                ),
            }

        return _guarded(runtime, state, "supervisor", _work)

    def make_agent_node(route: str):
        def agent_node(state: TicketState) -> TicketState:
            def _work() -> TicketState:
                ledger.take_step()
                agent = runtime.agent_for(route)
                attempt = state.get("attempt", 1)
                with traced_step(
                    f"{route}.execute",
                    kind="agent",
                    trace_id=state["ticket_id"],
                    attempt=attempt,
                ) as span:
                    if route == "refund_agent":
                        result: AgentResult = agent.run(
                            state["ticket_text"], state["ticket_id"], attempt=attempt
                        )
                    else:
                        result = agent.run(state["ticket_text"], attempt=attempt)
                    ledger.charge(runtime.settings.cost_per_tool_call, reason=f"{route}_tool_call")
                    span.set_attribute("agentops.confidence", result.confidence)
                    span.set_attribute("agentops.tool_error", bool(result.failed))
                    span.set_attribute("agentops.content", result.content)
                return {
                    "last_result": {
                        "content": result.content,
                        "confidence": result.confidence,
                        "tool_error": result.tool_error,
                        "data": result.data,
                    },
                    "events": _log(
                        state,
                        node=route,
                        attempt=attempt,
                        confidence=result.confidence,
                        tool_error=result.tool_error,
                    ),
                }

            return _guarded(runtime, state, route, _work)

        return agent_node

    def critique_node(state: TicketState) -> TicketState:
        def _work() -> TicketState:
            ledger.take_step()
            last = state["last_result"]
            result = AgentResult(
                content=last["content"],
                confidence=last["confidence"],
                tool_error=last["tool_error"],
                data=last.get("data", {}),
            )
            attempt = state.get("attempt", 1)
            with traced_step(
                "critique.review", kind="agent", trace_id=state["ticket_id"], attempt=attempt
            ) as span:
                decision: CritiqueDecision = run_critique(
                    result,
                    attempt=attempt,
                    max_retries=runtime.settings.max_retries_per_task,
                    llm=runtime.llm,
                    confidence_threshold=runtime.settings.confidence_threshold,
                )
                ledger.charge(runtime.settings.cost_per_llm_call, reason="critique_llm_call")
                span.set_attribute("agentops.verdict", decision.verdict)
                span.set_attribute("agentops.confidence", decision.confidence)
                span.set_attribute("agentops.rationale", decision.rationale)
            return {
                "critique": {
                    "verdict": decision.verdict,
                    "confidence": decision.confidence,
                    "rationale": decision.rationale,
                },
                "attempt": attempt + 1 if decision.verdict == "retry" else attempt,
                "events": _log(
                    state,
                    node="critique",
                    verdict=decision.verdict,
                    confidence=decision.confidence,
                    rationale=decision.rationale,
                ),
            }

        return _guarded(runtime, state, "critique", _work)

    def respond_node(state: TicketState) -> TicketState:
        with traced_step("respond.finalize", kind="agent", trace_id=state["ticket_id"]):
            pass
        return {
            "status": "completed",
            "final_answer": state["last_result"]["content"],
            "events": _log(state, node="respond", final_answer=state["last_result"]["content"]),
        }

    def escalate_node(state: TicketState) -> TicketState:
        reason = state.get("escalation_reason") or "supervisor_or_critique_requested_escalation"
        with traced_step(
            "escalate.human_handoff", kind="guardrail", trace_id=state["ticket_id"], reason=reason
        ):
            pass
        return {
            "status": "escalated",
            "escalation_reason": reason,
            "events": _log(state, node="escalate", reason=reason),
        }

    graph = StateGraph(TicketState)
    graph.add_node("supervisor", supervisor_node)
    for route in SUB_AGENT_ROUTES:
        graph.add_node(route, make_agent_node(route))
    graph.add_node("critique_review", critique_node)
    graph.add_node("respond", respond_node)
    graph.add_node("escalate", escalate_node)

    graph.set_entry_point("supervisor")

    def after_supervisor(state: TicketState) -> str:
        if state.get("guardrail_tripped"):
            return "escalate"
        return state["route"]

    graph.add_conditional_edges(
        "supervisor",
        after_supervisor,
        {**{route: route for route in SUB_AGENT_ROUTES}, "escalate": "escalate"},
    )

    def after_agent(state: TicketState) -> str:
        if state.get("guardrail_tripped"):
            return "escalate"
        return "critique_review"

    for route in SUB_AGENT_ROUTES:
        graph.add_conditional_edges(
            route, after_agent, {"critique_review": "critique_review", "escalate": "escalate"}
        )

    def after_critique(state: TicketState) -> str:
        if state.get("guardrail_tripped"):
            return "escalate"
        verdict = state["critique"]["verdict"]
        if verdict == "accept":
            return "respond"
        if verdict == "retry":
            return state["route"]
        return "escalate"

    graph.add_conditional_edges(
        "critique_review",
        after_critique,
        {**{route: route for route in SUB_AGENT_ROUTES}, "respond": "respond", "escalate": "escalate"},
    )

    graph.add_edge("respond", END)
    graph.add_edge("escalate", END)

    return graph.compile()
