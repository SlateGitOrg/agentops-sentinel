"""Order lookup tool.

Backed by a small bundled fixture "database". Two reserved order-id
prefixes let tests deterministically exercise failure handling without
any mocking framework:

- `FLAKY-*`  : simulates a transient backend blip. Fails on the first
               attempt, succeeds from the second attempt onward -- this
               is what the self-critique/retry loop is meant to recover
               from.
- `MISSING-*`: simulates a permanent *domain* outcome (no such order).
               This is a confident, correct answer ("not found"), not a
               tool error, so the critique loop accepts it immediately.
- `DOWN-*`   : simulates a permanent *tool* failure (backend never
               recovers). Retrying never helps; the critique loop
               should escalate once retries are exhausted rather than
               loop forever.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentops_sentinel.tools.errors import ToolError, ToolNotFoundError

_ORDERS: dict[str, dict] = {
    "ORD-1001": {
        "status": "delivered",
        "tracking": "1Z999AA10123456784",
        "total_usd": 129.99,
        "delivered_at": "2026-06-30",
    },
    "ORD-1002": {
        "status": "in_transit",
        "tracking": "1Z999AA10123456785",
        "total_usd": 59.50,
        "delivered_at": None,
    },
    "ORD-1003": {
        "status": "delivered",
        "tracking": "1Z999AA10123456786",
        "total_usd": 249.00,
        "delivered_at": "2026-07-01",
    },
}


@dataclass
class OrderRecord:
    order_id: str
    status: str
    tracking: str | None
    total_usd: float
    delivered_at: str | None


class OrderLookupTool:
    """Looks up an order by id in the bundled fixture store."""

    name = "order_lookup"

    def __init__(self, orders: dict[str, dict] | None = None) -> None:
        self._orders = orders if orders is not None else _ORDERS

    def run(self, order_id: str, attempt: int = 1) -> OrderRecord:
        if order_id.startswith("DOWN-"):
            raise ToolError(f"order-service unavailable looking up {order_id} (attempt {attempt})")
        if order_id.startswith("FLAKY-") and attempt < 2:
            raise ToolError(f"order-service timeout looking up {order_id} (attempt {attempt})")

        real_id = order_id
        if order_id.startswith("FLAKY-"):
            real_id = order_id[len("FLAKY-") :]
        if order_id.startswith("MISSING-") or real_id not in self._orders:
            raise ToolNotFoundError(f"no order found for id '{order_id}'")

        record = self._orders[real_id]
        return OrderRecord(
            order_id=real_id,
            status=record["status"],
            tracking=record["tracking"],
            total_usd=record["total_usd"],
            delivered_at=record["delivered_at"],
        )
