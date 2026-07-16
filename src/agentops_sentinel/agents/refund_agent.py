"""Refund sub-agent: answers "refund my order" style tickets.

If the ticket doesn't specify an amount, the agent looks up the order
total and refunds it in full -- a small but real bit of multi-tool
reasoning (order lookup feeding into the refund tool).
"""

from __future__ import annotations

import re

from agentops_sentinel.agents.base import AgentResult
from agentops_sentinel.agents.order_agent import extract_order_id
from agentops_sentinel.tools.errors import ToolError, ToolNotFoundError
from agentops_sentinel.tools.order_lookup import OrderLookupTool
from agentops_sentinel.tools.refund_tool import RefundExceedsOrderTotalError, RefundTool

_AMOUNT_RE = re.compile(r"\$(\d+(?:\.\d{1,2})?)")


def extract_amount(text: str) -> float | None:
    match = _AMOUNT_RE.search(text)
    return float(match.group(1)) if match else None


class RefundAgent:
    name = "refund_agent"

    def __init__(
        self,
        refund_tool: RefundTool | None = None,
        order_tool: OrderLookupTool | None = None,
    ) -> None:
        self._refund_tool = refund_tool or RefundTool()
        self._order_tool = order_tool or OrderLookupTool()

    def run(self, ticket_text: str, ticket_id: str, attempt: int = 1) -> AgentResult:
        order_id = extract_order_id(ticket_text)
        if order_id is None:
            return AgentResult(
                content="Could not find an order number in the ticket to refund.",
                confidence=0.2,
            )

        amount = extract_amount(ticket_text)
        if amount is None:
            try:
                order = self._order_tool.run(order_id, attempt=attempt)
                amount = order.total_usd
            except ToolNotFoundError:
                return AgentResult(
                    content=f"No order found matching '{order_id}'; cannot refund.",
                    confidence=0.85,
                    data={"order_id": order_id, "found": False},
                )
            except ToolError as exc:
                return AgentResult(
                    content=f"Could not determine refund amount: {exc}",
                    confidence=0.0,
                    tool_error=str(exc),
                )

        idempotency_key = f"{ticket_id}:{order_id}"
        try:
            record = self._refund_tool.run(
                order_id, amount_usd=amount, idempotency_key=idempotency_key, attempt=attempt
            )
        except ToolNotFoundError:
            return AgentResult(
                content=f"No order found matching '{order_id}'; cannot refund.",
                confidence=0.85,
                data={"order_id": order_id, "found": False},
            )
        except RefundExceedsOrderTotalError as exc:
            return AgentResult(
                content=str(exc),
                confidence=0.9,  # the tool correctly rejected an invalid refund
                data={"order_id": order_id, "rejected": True},
            )
        except ToolError as exc:
            return AgentResult(
                content=f"Refund failed: {exc}",
                confidence=0.0,
                tool_error=str(exc),
            )

        content = f"Refunded ${record.amount_usd:.2f} for order {record.order_id} ({record.status})."
        return AgentResult(
            content=content,
            confidence=0.97,
            data={
                "order_id": record.order_id,
                "amount_usd": record.amount_usd,
                "status": record.status,
            },
        )
