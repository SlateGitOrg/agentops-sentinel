"""Self-critique node: decides whether a sub-agent's result is good enough.

This is the heart of the reliability story: rather than trusting a
sub-agent's first answer, a critique pass looks at the *observed*
confidence and whether the underlying tool call errored, and chooses
to accept the result, retry the sub-agent (bounded by
`max_retries_per_task`), or escalate to a human. The decision itself is
made by the same `LLMClient.decide` primitive the supervisor uses, kept
consistent so a real model swaps in without changing this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentops_sentinel.agents.base import AgentResult
from agentops_sentinel.llm import LLMClient

CRITIQUE_CHOICES = ["accept", "retry", "escalate"]

_SYSTEM_PROMPT = (
    "You are a critique reviewer for an AI support agent's draft answer. "
    "Decide whether to 'accept' the answer, 'retry' the sub-agent once "
    "more, or 'escalate' to a human. Retry only if there is a real chance "
    "another attempt improves things (e.g. a transient tool error); "
    "escalate once retries are exhausted or the failure looks permanent."
)


@dataclass
class CritiqueDecision:
    verdict: str  # "accept" | "retry" | "escalate"
    confidence: float
    rationale: str


def run_critique(
    result: AgentResult,
    *,
    attempt: int,
    max_retries: int,
    llm: LLMClient,
    confidence_threshold: float = 0.6,
) -> CritiqueDecision:
    choices = list(CRITIQUE_CHOICES)
    if attempt > max_retries:
        # No budget left for another attempt -- retry is not on the table.
        choices = ["accept", "escalate"]

    prompt = (
        f"Draft answer: {result.content!r}\n"
        f"observed_confidence={result.confidence:.2f}\n"
        f"attempt={attempt}\n"
        f"tool_error={'true' if result.failed else 'false'}\n"
        f"max_retries={max_retries}\n"
        f"confidence_threshold={confidence_threshold:.2f}"
    )
    decision = llm.decide(system_prompt=_SYSTEM_PROMPT, user_prompt=prompt, choices=choices)
    return CritiqueDecision(
        verdict=decision.choice, confidence=decision.confidence, rationale=decision.rationale
    )
