"""End-to-end graph tests: the dollar-budget and step-count guardrails."""

from __future__ import annotations

from agentops_sentinel.config import Settings
from agentops_sentinel.runner import AgentRunner


class TestBudgetGuardrail:
    def test_tiny_budget_forces_escalation_before_completion(self):
        # Each LLM call costs 0.03 by default; the supervisor alone costs
        # that much, so a 0.02 budget is exceeded on the very first call.
        settings = Settings(budget_usd=0.02, cost_per_llm_call=0.03, cost_per_tool_call=0.01)
        result = AgentRunner(settings=settings).run(
            "How do I set up SSO?", ticket_id="budget-tiny"
        )
        assert result.status == "escalated"
        assert result.escalation_reason is not None
        assert "BudgetExceededError" in result.escalation_reason
        assert result.cost_used_usd > settings.budget_usd

    def test_generous_budget_completes_normally(self):
        settings = Settings(budget_usd=5.0)
        result = AgentRunner(settings=settings).run(
            "How do I set up SSO?", ticket_id="budget-generous"
        )
        assert result.status == "completed"


class TestStepLimitGuardrail:
    def test_step_limit_of_one_forces_escalation(self):
        # The supervisor's own routing decision already consumes one
        # step; capping max_steps at 1 means the sub-agent can never run.
        settings = Settings(max_steps=1)
        result = AgentRunner(settings=settings).run(
            "How do I set up SSO?", ticket_id="steps-tiny"
        )
        assert result.status == "escalated"
        assert "StepLimitExceededError" in result.escalation_reason

    def test_generous_step_limit_completes_normally(self):
        settings = Settings(max_steps=20)
        result = AgentRunner(settings=settings).run(
            "How do I set up SSO?", ticket_id="steps-generous"
        )
        assert result.status == "completed"
