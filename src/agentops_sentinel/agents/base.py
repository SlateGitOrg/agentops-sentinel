"""Shared types for specialized sub-agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """The outcome of one sub-agent attempt at handling a ticket."""

    content: str
    confidence: float  # 0..1, the sub-agent's own estimate of correctness
    tool_error: str | None = None  # set if the underlying tool call raised
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.tool_error is not None
