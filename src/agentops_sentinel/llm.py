"""LLM client abstraction.

The supervisor and the self-critique node both need one primitive:
"given context and a fixed set of choices, pick one, with a confidence
score and a rationale." `LLMClient.decide(...)` is that primitive,
implemented three ways:

- `FakeLLMClient`: deterministic, offline, zero-cost heuristic reasoner.
  This is the default provider (`AGENTOPS_LLM_PROVIDER=fake`, or simply
  no API key present) and is what the entire test suite runs against --
  it is not a stub, it genuinely implements keyword/context-based
  routing and confidence estimation so the graph's control flow
  (retry/escalate/budget) is exercised for real.
- `AnthropicLLMClient`: real calls to the Anthropic Messages API.
- `OpenAILLMClient`: real calls to the OpenAI Chat Completions API.

Both real clients are only imported/instantiated when explicitly
selected, so `pip install`-ing this package and running its tests never
requires network access or API keys.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from agentops_sentinel.config import Settings


@dataclass
class LLMDecision:
    choice: str
    confidence: float  # 0..1
    rationale: str


class LLMClient(Protocol):
    def decide(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        choices: list[str],
    ) -> LLMDecision: ...


_DECISION_SCHEMA_INSTRUCTION = (
    "Respond with ONLY a JSON object of the form "
    '{"choice": "<one of the allowed choices, verbatim>", '
    '"confidence": <float 0-1>, "rationale": "<one sentence>"}. '
    "No prose outside the JSON."
)


def _parse_json_decision(raw_text: str, choices: list[str]) -> LLMDecision:
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    payload = json.loads(match.group(0)) if match else {}
    choice = payload.get("choice", choices[0])
    if choice not in choices:
        choice = choices[0]
    confidence = float(payload.get("confidence", 0.5))
    confidence = min(max(confidence, 0.0), 1.0)
    rationale = str(payload.get("rationale", ""))
    return LLMDecision(choice=choice, confidence=confidence, rationale=rationale)


class AnthropicLLMClient:
    """Thin wrapper around `anthropic.Anthropic().messages.create(...)`."""

    def __init__(self, model: str, api_key: str | None = None) -> None:
        import anthropic  # imported lazily: real network dependency

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def decide(self, *, system_prompt: str, user_prompt: str, choices: list[str]) -> LLMDecision:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=256,
            system=f"{system_prompt}\n\nAllowed choices: {choices}\n{_DECISION_SCHEMA_INSTRUCTION}",
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in message.content if hasattr(block, "text"))
        return _parse_json_decision(text, choices)


class OpenAILLMClient:
    """Thin wrapper around `openai.OpenAI().chat.completions.create(...)`."""

    def __init__(self, model: str, api_key: str | None = None) -> None:
        import openai  # imported lazily: real network dependency

        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def decide(self, *, system_prompt: str, user_prompt: str, choices: list[str]) -> LLMDecision:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": f"{system_prompt}\n\nAllowed choices: {choices}\n{_DECISION_SCHEMA_INSTRUCTION}",
                },
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=256,
        )
        text = response.choices[0].message.content or ""
        return _parse_json_decision(text, choices)


# --- Deterministic offline reasoner -----------------------------------------

_KB_HINTS = (
    "how do i",
    "how to",
    "documentation",
    "docs",
    "setup",
    "configure",
    "integration",
    "error code",
    "faq",
    "what is",
)
_ORDER_HINTS = ("order", "shipment", "shipping", "tracking", "delivery", "package", "invoice")
_REFUND_HINTS = ("refund", "charge back", "money back", "cancel my", "reimburse", "overcharged")
_ESCALATE_HINTS = ("lawyer", "legal", "furious", "unacceptable", "fraud", "threat", "sue")


def _keyword_score(text: str, hints: tuple[str, ...], base: float = 0.55, step: float = 0.15) -> float:
    text_lower = text.lower()
    hits = sum(1 for hint in hints if hint in text_lower)
    if hits == 0:
        return 0.0
    return min(1.0, base + step * hits)


class FakeLLMClient:
    """Deterministic, offline stand-in for a real LLM.

    Not a "mock that always returns X" -- it inspects the actual prompt
    text and the actual choice set and produces a plausible, *varying*
    decision + confidence, which is what lets the retry/critique/budget
    logic in the graph be exercised meaningfully by the test suite
    without any network access.
    """

    def decide(self, *, system_prompt: str, user_prompt: str, choices: list[str]) -> LLMDecision:
        del system_prompt  # not needed by the heuristic reasoner
        text = user_prompt

        scored: dict[str, float] = {}
        if "kb_agent" in choices or "kb_search" in choices:
            key = "kb_agent" if "kb_agent" in choices else "kb_search"
            scored[key] = _keyword_score(text, _KB_HINTS)
        if "order_agent" in choices or "order_lookup" in choices:
            key = "order_agent" if "order_agent" in choices else "order_lookup"
            scored[key] = _keyword_score(text, _ORDER_HINTS)
        if "refund_agent" in choices or "refund" in choices:
            key = "refund_agent" if "refund_agent" in choices else "refund"
            # Refund intent is a more specific/discriminative signal than the
            # generic "order" keyword (a refund ticket almost always also
            # mentions an order), so give it a higher base score to break
            # ties in the refund sub-agent's favor.
            scored[key] = _keyword_score(text, _REFUND_HINTS, base=0.65, step=0.15)
        if "escalate" in choices:
            scored["escalate"] = _keyword_score(text, _ESCALATE_HINTS, base=0.7, step=0.15)

        # Critique-style choices ("accept" [/ "retry"] / "escalate") are
        # driven by an explicit numeric confidence embedded in the prompt by
        # the caller (see agents/critique.py), not keyword-matched.
        if "accept" in choices and "observed_confidence=" in text:
            can_retry = "retry" in choices
            embedded = re.search(r"observed_confidence=([0-9.]+)", text)
            observed = float(embedded.group(1)) if embedded else 0.5
            attempt_match = re.search(r"attempt=(\d+)", text)
            attempt = int(attempt_match.group(1)) if attempt_match else 1
            threshold_match = re.search(r"confidence_threshold=([0-9.]+)", text)
            threshold = float(threshold_match.group(1)) if threshold_match else 0.6
            has_error = "tool_error=true" in text

            if has_error:
                if can_retry and attempt < 2:
                    return LLMDecision(
                        choice="retry", confidence=0.7, rationale="Tool call failed once; retrying."
                    )
                return LLMDecision(
                    choice="escalate",
                    confidence=0.9,
                    rationale="Tool failed and no retries remain; escalating to a human.",
                )
            if observed >= threshold:
                return LLMDecision(
                    choice="accept",
                    confidence=observed,
                    rationale="Sub-agent result is confident and well-grounded.",
                )
            if can_retry and attempt < 2:
                return LLMDecision(
                    choice="retry",
                    confidence=1 - observed,
                    rationale="Sub-agent result had low confidence; retrying once.",
                )
            if "escalate" in choices:
                return LLMDecision(
                    choice="escalate",
                    confidence=0.85,
                    rationale="Confidence stayed low and no retries remain; needs a human.",
                )
            return LLMDecision(
                choice="accept",
                confidence=observed,
                rationale="Accepting best-effort result; no escalation path available.",
            )

        if not scored or all(v == 0.0 for v in scored.values()):
            # Nothing matched strongly -- fall back to the first non-escalate
            # choice with modest confidence, mirroring a real LLM hedging.
            fallback = next((c for c in choices if c != "escalate"), choices[0])
            return LLMDecision(
                choice=fallback,
                confidence=0.5,
                rationale="No strong signal in the ticket text; best-effort routing.",
            )

        best_choice = max(scored, key=scored.get)
        return LLMDecision(
            choice=best_choice,
            confidence=scored[best_choice],
            rationale=f"Keyword signal strongly matched the '{best_choice}' route.",
        )


def build_llm_client(settings: Settings) -> LLMClient:
    """Factory: build the configured LLM client.

    Defaults to the offline `FakeLLMClient` unless a real provider is
    explicitly requested *and* its API key is present in the
    environment -- this makes "works offline out of the box" the path
    of least resistance rather than an opt-in.
    """
    import os

    provider = settings.llm_provider.lower()
    if provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicLLMClient(model=settings.anthropic_model)
    if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
        return OpenAILLMClient(model=settings.openai_model)
    return FakeLLMClient()
