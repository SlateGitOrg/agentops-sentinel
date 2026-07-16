"""Refund processing tool.

Operates against the same bundled order fixtures as `OrderLookupTool`.
Enforces a real domain invariant (can't refund more than the order
total) and supports the same `FLAKY-`/`MISSING-` prefixes for
deterministic transient/permanent failure simulation, plus idempotent
replay: calling `run` twice with the same `idempotency_key` returns the
original result instead of double-refunding.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentops_sentinel.tools.errors import ToolError, ToolNotFoundError
from agentops_sentinel.tools.order_lookup import _ORDERS


class RefundExceedsOrderTotalError(ToolError):
    def __init__(self, amount: float, total: float) -> None:
        super().__init__(f"refund amount ${amount:.2f} exceeds order total ${total:.2f}")


@dataclass
class RefundRecord:
    order_id: str
    amount_usd: float
    idempotency_key: str
    status: str  # "processed" | "replayed"


class RefundTool:
    """Processes (simulated) refunds with idempotency and a hard cap."""

    name = "refund"

    def __init__(self, orders: dict[str, dict] | None = None) -> None:
        self._orders = orders if orders is not None else _ORDERS
        self._processed: dict[str, RefundRecord] = {}

    def run(
        self,
        order_id: str,
        amount_usd: float,
        idempotency_key: str,
        attempt: int = 1,
    ) -> RefundRecord:
        if idempotency_key in self._processed:
            prior = self._processed[idempotency_key]
            return RefundRecord(
                order_id=prior.order_id,
                amount_usd=prior.amount_usd,
                idempotency_key=idempotency_key,
                status="replayed",
            )

        if order_id.startswith("DOWN-"):
            raise ToolError(f"payment-gateway unavailable refunding {order_id} (attempt {attempt})")
        if order_id.startswith("FLAKY-") and attempt < 2:
            raise ToolError(f"payment-gateway timeout refunding {order_id} (attempt {attempt})")

        real_id = order_id[len("FLAKY-") :] if order_id.startswith("FLAKY-") else order_id
        if order_id.startswith("MISSING-") or real_id not in self._orders:
            raise ToolNotFoundError(f"no order found for id '{order_id}'")

        total = self._orders[real_id]["total_usd"]
        if amount_usd > total + 1e-9:
            raise RefundExceedsOrderTotalError(amount_usd, total)

        record = RefundRecord(
            order_id=real_id, amount_usd=amount_usd, idempotency_key=idempotency_key, status="processed"
        )
        self._processed[idempotency_key] = record
        return record
