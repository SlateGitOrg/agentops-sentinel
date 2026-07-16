"""Guardrails: step limits, dollar budget, per-step timeout, human escalation.

These are the safety rails that keep an agentic loop from running away:
looping forever, spending unbounded money on LLM/tool calls, hanging on
a slow tool, or confidently doing the wrong thing. Every guardrail trip
is a first-class, traceable event (see `agentops_sentinel.tracing`) and
raises a typed exception the graph can catch and route to escalation.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Callable, TypeVar

T = TypeVar("T")


class GuardrailTripped(Exception):
    """Base class for all guardrail violations."""


class BudgetExceededError(GuardrailTripped):
    def __init__(self, spent: float, budget: float) -> None:
        self.spent = spent
        self.budget = budget
        super().__init__(f"Budget exceeded: spent ${spent:.4f} of ${budget:.4f}")


class StepLimitExceededError(GuardrailTripped):
    def __init__(self, steps: int, max_steps: int) -> None:
        self.steps = steps
        self.max_steps = max_steps
        super().__init__(f"Step limit exceeded: {steps} of {max_steps} max steps")


class StepTimeoutError(GuardrailTripped):
    def __init__(self, step_name: str, timeout_s: float) -> None:
        self.step_name = step_name
        self.timeout_s = timeout_s
        super().__init__(f"Step '{step_name}' exceeded timeout of {timeout_s}s")


@dataclass
class GuardrailLedger:
    """Mutable, per-run bookkeeping for budget and step guardrails.

    One ledger is created per ticket run and threaded through the graph
    state so every node can charge against the same budget/step count.
    """

    max_steps: int
    budget_usd: float
    steps_used: int = 0
    cost_used_usd: float = 0.0
    charges: list[dict] = field(default_factory=list)

    def charge(self, amount_usd: float, *, reason: str) -> None:
        """Record a spend. Raises BudgetExceededError if it pushes us over."""
        projected = self.cost_used_usd + amount_usd
        self.charges.append({"reason": reason, "amount_usd": amount_usd})
        self.cost_used_usd = projected
        if projected > self.budget_usd:
            raise BudgetExceededError(projected, self.budget_usd)

    def take_step(self) -> None:
        """Consume one step of the step budget. Raises StepLimitExceededError."""
        self.steps_used += 1
        if self.steps_used > self.max_steps:
            raise StepLimitExceededError(self.steps_used, self.max_steps)

    def remaining_budget(self) -> float:
        return max(0.0, self.budget_usd - self.cost_used_usd)

    def remaining_steps(self) -> int:
        return max(0, self.max_steps - self.steps_used)

    def to_dict(self) -> dict:
        return {
            "max_steps": self.max_steps,
            "budget_usd": self.budget_usd,
            "steps_used": self.steps_used,
            "cost_used_usd": round(self.cost_used_usd, 4),
        }


def run_with_timeout(fn: Callable[[], T], timeout_s: float, *, step_name: str) -> T:
    """Run `fn` (a zero-arg callable) with a hard wall-clock timeout.

    Uses a worker thread rather than signals so it works identically on
    macOS/Linux/containers and doesn't clash with async runtimes. Note
    this deliberately does NOT use `ThreadPoolExecutor` as a context
    manager: `__exit__` calls `shutdown(wait=True)`, which would block
    the caller until the hung function actually finishes -- defeating
    the point of a timeout. Instead we shut down with `wait=False`: the
    orphaned thread keeps running in the background (harmless for the
    pure, side-effect-free steps this guards) while control returns to
    the caller immediately.
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError as exc:
        raise StepTimeoutError(step_name, timeout_s) from exc
    finally:
        pool.shutdown(wait=False)
