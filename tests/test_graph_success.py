"""End-to-end graph tests: happy paths for each sub-agent."""

from __future__ import annotations

from agentops_sentinel.config import Settings
from agentops_sentinel.runner import AgentRunner
from agentops_sentinel.tracing import DecisionTraceStore


def _runner() -> AgentRunner:
    return AgentRunner(settings=Settings.load())


class TestKnowledgeBaseHappyPath:
    def test_kb_question_resolves_without_escalation(self):
        result = _runner().run("How do I configure API rate limits?", ticket_id="kb-1")
        assert result.status == "completed"
        assert result.route == "kb_agent"
        assert "KB-100" in result.final_answer
        assert result.escalation_reason is None
        assert result.steps_used > 0

    def test_run_is_persisted_to_session_store(self):
        runner = _runner()
        result = runner.run("What is the difference between plans?", ticket_id="kb-2")
        stored = runner.session_store.get_run("kb-2")
        assert stored is not None
        assert stored["status"] == result.status
        assert stored["final_answer"] == result.final_answer


class TestOrderLookupHappyPath:
    def test_order_status_question_resolves(self):
        result = _runner().run("What's the status of order ORD-1001?", ticket_id="order-1")
        assert result.status == "completed"
        assert result.route == "order_agent"
        assert "delivered" in result.final_answer


class TestRefundHappyPath:
    def test_refund_request_resolves(self):
        result = _runner().run(
            "Please refund my order ORD-1003, I want my money back", ticket_id="refund-1"
        )
        assert result.status == "completed"
        assert result.route == "refund_agent"
        assert "Refunded" in result.final_answer
        assert "249.00" in result.final_answer


class TestDecisionTraceIsRecorded:
    def test_completed_run_has_a_full_decision_trace(self, isolated_tracing: DecisionTraceStore):
        runner = _runner()
        result = runner.run("How do I reset my password?", ticket_id="trace-1")
        spans = isolated_tracing.get_trace("trace-1")
        names = [s["name"] for s in spans]
        assert "supervisor.route" in names
        assert "kb_agent.execute" in names
        assert "critique.review" in names
        assert "respond.finalize" in names
        assert result.status == "completed"
        assert all(s["status"] == "OK" for s in spans)
