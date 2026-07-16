"""Unit tests for guardrails: budget, step-count, and timeout."""

from __future__ import annotations

import time

import pytest

from agentops_sentinel.guardrails import (
    BudgetExceededError,
    GuardrailLedger,
    StepLimitExceededError,
    StepTimeoutError,
    run_with_timeout,
)


class TestGuardrailLedger:
    def test_charge_under_budget_is_fine(self):
        ledger = GuardrailLedger(max_steps=10, budget_usd=1.0)
        ledger.charge(0.3, reason="llm_call")
        ledger.charge(0.3, reason="tool_call")
        assert ledger.cost_used_usd == pytest.approx(0.6)
        assert ledger.remaining_budget() == pytest.approx(0.4)

    def test_charge_over_budget_raises(self):
        ledger = GuardrailLedger(max_steps=10, budget_usd=0.5)
        ledger.charge(0.3, reason="llm_call")
        with pytest.raises(BudgetExceededError) as exc_info:
            ledger.charge(0.3, reason="tool_call")
        assert exc_info.value.spent == pytest.approx(0.6)
        assert exc_info.value.budget == 0.5

    def test_step_within_limit_is_fine(self):
        ledger = GuardrailLedger(max_steps=3, budget_usd=10.0)
        ledger.take_step()
        ledger.take_step()
        ledger.take_step()
        assert ledger.steps_used == 3
        assert ledger.remaining_steps() == 0

    def test_step_over_limit_raises(self):
        ledger = GuardrailLedger(max_steps=1, budget_usd=10.0)
        ledger.take_step()
        with pytest.raises(StepLimitExceededError) as exc_info:
            ledger.take_step()
        assert exc_info.value.steps == 2
        assert exc_info.value.max_steps == 1

    def test_to_dict_reports_usage(self):
        ledger = GuardrailLedger(max_steps=5, budget_usd=1.0)
        ledger.take_step()
        ledger.charge(0.25, reason="x")
        snapshot = ledger.to_dict()
        assert snapshot["steps_used"] == 1
        assert snapshot["cost_used_usd"] == 0.25


class TestTimeoutGuard:
    def test_fast_function_returns_value(self):
        result = run_with_timeout(lambda: 42, timeout_s=1.0, step_name="fast")
        assert result == 42

    def test_slow_function_raises_timeout(self):
        def _slow():
            time.sleep(0.5)
            return "too late"

        with pytest.raises(StepTimeoutError) as exc_info:
            run_with_timeout(_slow, timeout_s=0.05, step_name="slow_step")
        assert exc_info.value.step_name == "slow_step"

    def test_exception_inside_function_propagates(self):
        def _boom():
            raise ValueError("kaboom")

        with pytest.raises(ValueError, match="kaboom"):
            run_with_timeout(_boom, timeout_s=1.0, step_name="boom_step")
