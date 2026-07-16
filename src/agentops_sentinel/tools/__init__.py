"""Domain tools for the support-ticket-triage sub-agents.

Each tool is a small, dependency-free class operating over bundled
in-memory fixture data (no network, no database) so the whole system
is offline-verifiable. Tools can fail -- both "expected" domain
failures (order not found) and simulated *transient* failures (a
flaky backend) used to exercise the self-critique/retry loop in tests.
"""

from agentops_sentinel.tools.errors import ToolError, ToolNotFoundError
from agentops_sentinel.tools.kb_search import KnowledgeBaseSearchTool
from agentops_sentinel.tools.order_lookup import OrderLookupTool
from agentops_sentinel.tools.refund_tool import RefundTool

__all__ = [
    "ToolError",
    "ToolNotFoundError",
    "KnowledgeBaseSearchTool",
    "OrderLookupTool",
    "RefundTool",
]
