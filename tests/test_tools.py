"""Unit tests for the bundled domain tools."""

from __future__ import annotations

import pytest

from agentops_sentinel.tools.errors import ToolError, ToolNotFoundError
from agentops_sentinel.tools.kb_search import KnowledgeBaseSearchTool
from agentops_sentinel.tools.order_lookup import OrderLookupTool
from agentops_sentinel.tools.refund_tool import RefundExceedsOrderTotalError, RefundTool


class TestKnowledgeBaseSearchTool:
    def test_finds_relevant_article(self):
        tool = KnowledgeBaseSearchTool()
        result = tool.run("How do I configure API rate limits?")
        assert result.article_id == "KB-100"
        assert result.score > 0.5

    def test_no_match_returns_empty_result(self):
        tool = KnowledgeBaseSearchTool()
        result = tool.run("zzz qqq xyzzy plugh")
        assert result.article_id == ""
        assert result.score == 0.0

    def test_empty_query_is_handled(self):
        tool = KnowledgeBaseSearchTool()
        result = tool.run("")
        assert result.article_id == ""


class TestOrderLookupTool:
    def test_found_order(self):
        tool = OrderLookupTool()
        record = tool.run("ORD-1001")
        assert record.status == "delivered"
        assert record.total_usd == 129.99

    def test_missing_order_raises_not_found(self):
        tool = OrderLookupTool()
        with pytest.raises(ToolNotFoundError):
            tool.run("MISSING-ORD-0000")

    def test_unknown_order_id_raises_not_found(self):
        tool = OrderLookupTool()
        with pytest.raises(ToolNotFoundError):
            tool.run("ORD-9999")

    def test_flaky_order_fails_first_attempt_then_succeeds(self):
        tool = OrderLookupTool()
        with pytest.raises(ToolError):
            tool.run("FLAKY-ORD-1001", attempt=1)
        record = tool.run("FLAKY-ORD-1001", attempt=2)
        assert record.order_id == "ORD-1001"

    def test_down_order_always_fails(self):
        tool = OrderLookupTool()
        with pytest.raises(ToolError):
            tool.run("DOWN-ORD-1001", attempt=1)
        with pytest.raises(ToolError):
            tool.run("DOWN-ORD-1001", attempt=5)


class TestRefundTool:
    def test_full_refund_succeeds(self):
        tool = RefundTool()
        record = tool.run("ORD-1002", amount_usd=59.50, idempotency_key="k1")
        assert record.status == "processed"
        assert record.amount_usd == 59.50

    def test_idempotent_replay_returns_same_result(self):
        tool = RefundTool()
        first = tool.run("ORD-1002", amount_usd=59.50, idempotency_key="k1")
        second = tool.run("ORD-1002", amount_usd=59.50, idempotency_key="k1")
        assert second.status == "replayed"
        assert second.amount_usd == first.amount_usd

    def test_refund_over_total_is_rejected(self):
        tool = RefundTool()
        with pytest.raises(RefundExceedsOrderTotalError):
            tool.run("ORD-1002", amount_usd=999.0, idempotency_key="k2")

    def test_refund_missing_order_raises_not_found(self):
        tool = RefundTool()
        with pytest.raises(ToolNotFoundError):
            tool.run("MISSING-ORD-0000", amount_usd=10.0, idempotency_key="k3")

    def test_flaky_refund_fails_then_succeeds(self):
        tool = RefundTool()
        with pytest.raises(ToolError):
            tool.run("FLAKY-ORD-1003", amount_usd=10.0, idempotency_key="k4", attempt=1)
        record = tool.run("FLAKY-ORD-1003", amount_usd=10.0, idempotency_key="k4", attempt=2)
        assert record.status == "processed"

    def test_down_refund_always_fails(self):
        tool = RefundTool()
        with pytest.raises(ToolError):
            tool.run("DOWN-ORD-1001", amount_usd=10.0, idempotency_key="k5", attempt=3)
