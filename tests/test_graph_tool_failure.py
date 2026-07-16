"""End-to-end graph tests: tool failures recovered (or not) by the
self-critique/retry loop."""

from __future__ import annotations

from agentops_sentinel.config import Settings
from agentops_sentinel.runner import AgentRunner


def _runner(**overrides) -> AgentRunner:
    return AgentRunner(settings=Settings(**overrides))


class TestTransientToolFailureIsRecovered:
    def test_flaky_order_lookup_succeeds_after_one_retry(self):
        result = _runner().run("Where is my order FLAKY-ORD-1001?", ticket_id="flaky-order")
        assert result.status == "completed"
        assert result.route == "order_agent"
        assert "delivered" in result.final_answer

        retry_events = [e for e in result.events if e.get("node") == "critique" and e["verdict"] == "retry"]
        assert len(retry_events) == 1
        agent_attempts = [e for e in result.events if e.get("node") == "order_agent"]
        assert len(agent_attempts) == 2  # first attempt failed, second succeeded

    def test_flaky_refund_succeeds_after_one_retry(self):
        result = _runner().run(
            "Please refund my order FLAKY-ORD-1002, refund me now", ticket_id="flaky-refund"
        )
        assert result.status == "completed"
        assert result.route == "refund_agent"
        assert "Refunded" in result.final_answer


class TestPermanentToolFailureEscalates:
    def test_down_order_service_escalates_after_retries_exhausted(self):
        result = _runner(max_retries_per_task=1).run(
            "Where is my order DOWN-ORD-1001?", ticket_id="down-order"
        )
        assert result.status == "escalated"
        assert result.route == "order_agent"
        assert result.escalation_reason is not None

        tool_errors = [e for e in result.events if e.get("node") == "order_agent"]
        assert all(e["tool_error"] is not None for e in tool_errors)


class TestNotFoundIsAConfidentAnswerNotAFailure:
    def test_missing_order_completes_with_a_not_found_answer(self):
        result = _runner().run("Where is my order MISSING-ORD-0000?", ticket_id="missing-order")
        assert result.status == "completed"
        assert "No order found" in result.final_answer
