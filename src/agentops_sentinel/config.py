"""Runtime configuration for agentops-sentinel.

All values are overridable via environment variables so the same code
runs identically in tests (fully offline), in Docker, and in production.
No secrets have defaults baked in -- API keys are read from the
environment only, and if absent the system falls back to the
deterministic offline LLM provider (see `agentops_sentinel.llm`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    """Immutable settings snapshot. Build one with `Settings.load()`."""

    # -- LLM provider selection -------------------------------------------------
    # "fake" (default, offline/deterministic), "anthropic", or "openai".
    llm_provider: str = field(default_factory=lambda: _env_str("AGENTOPS_LLM_PROVIDER", "fake"))
    anthropic_model: str = field(
        default_factory=lambda: _env_str("AGENTOPS_ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
    )
    openai_model: str = field(default_factory=lambda: _env_str("AGENTOPS_OPENAI_MODEL", "gpt-4o-mini"))

    # -- Guardrails ---------------------------------------------------------
    max_steps: int = field(default_factory=lambda: _env_int("AGENTOPS_MAX_STEPS", 6))
    max_retries_per_task: int = field(
        default_factory=lambda: _env_int("AGENTOPS_MAX_RETRIES_PER_TASK", 2)
    )
    budget_usd: float = field(default_factory=lambda: _env_float("AGENTOPS_BUDGET_USD", 0.50))
    step_timeout_s: float = field(default_factory=lambda: _env_float("AGENTOPS_STEP_TIMEOUT_S", 8.0))
    confidence_threshold: float = field(
        default_factory=lambda: _env_float("AGENTOPS_CONFIDENCE_THRESHOLD", 0.6)
    )

    # -- Simulated per-call costs (USD) so the budget guard has something to bite on ---
    cost_per_llm_call: float = field(
        default_factory=lambda: _env_float("AGENTOPS_COST_PER_LLM_CALL", 0.03)
    )
    cost_per_tool_call: float = field(
        default_factory=lambda: _env_float("AGENTOPS_COST_PER_TOOL_CALL", 0.01)
    )

    # -- Storage --------------------------------------------------------------
    redis_url: str = field(default_factory=lambda: _env_str("AGENTOPS_REDIS_URL", ""))

    # -- Tracing ----------------------------------------------------------------
    otel_console_export: bool = field(
        default_factory=lambda: _env_str("AGENTOPS_OTEL_CONSOLE_EXPORT", "false").lower() == "true"
    )
    service_name: str = field(
        default_factory=lambda: _env_str("AGENTOPS_SERVICE_NAME", "agentops-sentinel")
    )

    @classmethod
    def load(cls) -> "Settings":
        return cls()


def get_settings() -> Settings:
    """Fresh settings snapshot, read from the current environment.

    Deliberately not cached: tests monkeypatch environment variables
    per-case and expect a new call to pick them up.
    """
    return Settings.load()
