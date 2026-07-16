"""Direct (graph-bypassing) unit tests for the specialized sub-agents.

Complements the end-to-end graph tests by exercising less common
branches (missing identifiers, refunds exceeding the order total,
etc.) in isolation.
"""

from __future__ import annotations

from agentops_sentinel.agents.kb_agent import KnowledgeBaseAgent
from agentops_sentinel.agents.order_agent import OrderAgent, extract_order_id
from agentops_sentinel.agents.refund_agent import RefundAgent, extract_amount


class TestKnowledgeBaseAgent:
    def test_no_match_yields_low_confidence(self):
        agent = KnowledgeBaseAgent()
        result = agent.run("completely unrelated gibberish text")
        assert result.confidence < 0.6
        assert not result.failed


class TestOrderAgent:
    def test_no_order_id_in_ticket(self):
        agent = OrderAgent()
        result = agent.run("I have a general question")
        assert "Could not find an order number" in result.content
        assert result.confidence < 0.6

    def test_extract_order_id_variants(self):
        assert extract_order_id("order ORD-1001 please") == "ORD-1001"
        assert extract_order_id("order FLAKY-ORD-1001") == "FLAKY-ORD-1001"
        assert extract_order_id("order DOWN-ORD-1001") == "DOWN-ORD-1001"
        assert extract_order_id("no id here") is None


class TestRefundAgent:
    def test_no_order_id_in_ticket(self):
        agent = RefundAgent()
        result = agent.run("I want a refund please", ticket_id="t1")
        assert "Could not find an order number" in result.content
        assert result.confidence < 0.6

    def test_refund_missing_order_via_amount_lookup_path(self):
        agent = RefundAgent()
        result = agent.run("Refund order MISSING-ORD-0000", ticket_id="t2")
        assert "No order found" in result.content
        assert result.data.get("found") is False

    def test_refund_exceeding_order_total_is_rejected(self):
        agent = RefundAgent()
        # explicit $ amount skips the order-total lookup and goes straight
        # to the refund tool, which enforces the "can't exceed total" rule
        result = agent.run("Refund $99999.00 for order ORD-1001", ticket_id="t3")
        assert "exceeds order total" in result.content
        assert result.data.get("rejected") is True

    def test_refund_with_explicit_amount_on_missing_order(self):
        agent = RefundAgent()
        result = agent.run("Refund $10.00 for order MISSING-ORD-0000", ticket_id="t4")
        assert "No order found" in result.content

    def test_refund_permanent_tool_failure_with_explicit_amount(self):
        agent = RefundAgent()
        result = agent.run("Refund $10.00 for order DOWN-ORD-1001", ticket_id="t5", attempt=3)
        assert result.failed
        assert "Refund failed" in result.content

    def test_refund_transient_failure_during_amount_lookup(self):
        agent = RefundAgent()
        result = agent.run("Refund my order FLAKY-ORD-1001", ticket_id="t6", attempt=1)
        assert result.failed
        assert "Could not determine refund amount" in result.content

    def test_extract_amount_variants(self):
        assert extract_amount("please refund $42.50 now") == 42.50
        assert extract_amount("no amount mentioned") is None
