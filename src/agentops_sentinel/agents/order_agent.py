"""Order-lookup sub-agent: answers "where is my order" style tickets."""

from __future__ import annotations

import re

from agentops_sentinel.agents.base import AgentResult
from agentops_sentinel.tools.errors import ToolError, ToolNotFoundError
from agentops_sentinel.tools.order_lookup import OrderLookupTool

_ORDER_ID_RE = re.compile(r"(?:FLAKY-|MISSING-|DOWN-)?ORD-[A-Za-z0-9]+")


def extract_order_id(text: str) -> str | None:
    match = _ORDER_ID_RE.search(text)
    return match.group(0) if match else None


class OrderAgent:
    name = "order_agent"

    def __init__(self, tool: OrderLookupTool | None = None) -> None:
        self._tool = tool or OrderLookupTool()

    def run(self, ticket_text: str, attempt: int = 1) -> AgentResult:
        order_id = extract_order_id(ticket_text)
        if order_id is None:
            return AgentResult(
                content="Could not find an order number in the ticket to look up.",
                confidence=0.2,
            )
        try:
            record = self._tool.run(order_id, attempt=attempt)
        except ToolNotFoundError as exc:
            return AgentResult(
                content=f"No order found matching '{order_id}'.",
                confidence=0.9,  # the *lookup* succeeded in confidently determining "not found"
                data={"order_id": order_id, "found": False},
                tool_error=None if isinstance(exc, ToolNotFoundError) else str(exc),
            )
        except ToolError as exc:
            return AgentResult(
                content=f"Order lookup failed: {exc}",
                confidence=0.0,
                tool_error=str(exc),
            )

        content = (
            f"Order {record.order_id} is currently '{record.status}'. "
            f"Tracking: {record.tracking}. Total: ${record.total_usd:.2f}."
        )
        return AgentResult(
            content=content,
            confidence=0.95,
            data={
                "order_id": record.order_id,
                "status": record.status,
                "tracking": record.tracking,
                "total_usd": record.total_usd,
            },
        )
