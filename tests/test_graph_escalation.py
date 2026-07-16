"""End-to-end graph tests: direct human-in-the-loop escalation."""

from __future__ import annotations

from agentops_sentinel.config import Settings
from agentops_sentinel.runner import AgentRunner


class TestSupervisorDirectEscalation:
    def test_hostile_ticket_escalates_without_touching_a_sub_agent(self):
        result = AgentRunner(settings=Settings.load()).run(
            "This is unacceptable, I will sue you, get me a lawyer immediately.",
            ticket_id="hostile-1",
        )
        assert result.status == "escalated"
        assert result.route == "escalate"
        assert result.escalation_reason is not None
        # only the supervisor step should have run -- no sub-agent, no critique
        node_names = {e.get("node") for e in result.events}
        assert node_names == {"supervisor", "escalate"}

    def test_escalated_run_has_no_final_answer(self):
        result = AgentRunner(settings=Settings.load()).run(
            "This is fraud, I demand a lawyer.", ticket_id="hostile-2"
        )
        assert result.status == "escalated"
        assert result.final_answer is None


class TestCritiqueDrivenEscalation:
    def test_repeated_low_confidence_kb_result_eventually_escalates(self):
        # A query with zero keyword overlap against the bundled KB always
        # scores 0.0 confidence, so even after exhausting retries the
        # critique loop must hand off to a human instead of looping
        # forever or fabricating a confident answer.
        settings = Settings(max_retries_per_task=1, max_steps=10)
        result = AgentRunner(settings=settings).run(
            "asdf qwer zxcv unrelated nonsense gibberish", ticket_id="low-confidence-kb"
        )
        assert result.status == "escalated"
        assert result.escalation_reason is not None
