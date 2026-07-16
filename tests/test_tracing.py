"""Unit tests for the OpenTelemetry decision-trace sidecar."""

from __future__ import annotations

from agentops_sentinel.tracing import DecisionTraceStore, configure_tracing, traced_step


class TestTracedStep:
    def test_successful_step_records_ok_span(self, isolated_tracing: DecisionTraceStore):
        with traced_step("kb_agent.search", kind="agent", trace_id="t1", query="hello") as span:
            span.set_attribute("agentops.confidence", 0.8)

        spans = isolated_tracing.get_trace("t1")
        assert len(spans) == 1
        assert spans[0]["name"] == "kb_agent.search"
        assert spans[0]["kind"] == "agent"
        assert spans[0]["status"] == "OK"
        assert spans[0]["attributes"]["agentops.query"] == "hello"
        assert spans[0]["attributes"]["agentops.confidence"] == 0.8

    def test_failed_step_records_error_span_and_reraises(self, isolated_tracing: DecisionTraceStore):
        try:
            with traced_step("order_agent.lookup", kind="agent", trace_id="t2"):
                raise ValueError("boom")
        except ValueError:
            pass
        else:
            raise AssertionError("expected traced_step to re-raise")

        spans = isolated_tracing.get_trace("t2")
        assert len(spans) == 1
        assert spans[0]["status"] == "ERROR"
        assert "boom" in spans[0]["error"]

    def test_traces_are_isolated_by_trace_id(self, isolated_tracing: DecisionTraceStore):
        with traced_step("a", kind="supervisor", trace_id="alpha"):
            pass
        with traced_step("b", kind="supervisor", trace_id="beta"):
            pass

        assert len(isolated_tracing.get_trace("alpha")) == 1
        assert len(isolated_tracing.get_trace("beta")) == 1
        assert set(isolated_tracing.list_traces()) == {"alpha", "beta"}

    def test_nested_spans_share_trace_id_with_parent_child_link(
        self, isolated_tracing: DecisionTraceStore
    ):
        with traced_step("outer", kind="supervisor", trace_id="nested"):
            with traced_step("inner", kind="agent", trace_id="nested"):
                pass

        spans = {s["name"]: s for s in isolated_tracing.get_trace("nested")}
        assert spans["inner"]["parent_span_id"] == spans["outer"]["span_id"]

    def test_unknown_trace_returns_empty_list(self, isolated_tracing: DecisionTraceStore):
        assert isolated_tracing.get_trace("does-not-exist") == []


class TestDecisionTraceStoreEviction:
    def test_store_bounds_memory_by_evicting_oldest_trace(self):
        store = DecisionTraceStore(max_tickets=2)
        configure_tracing(service_name="eviction-test", store=store)
        for trace_id in ("t1", "t2", "t3"):
            with traced_step("step", kind="agent", trace_id=trace_id):
                pass
        # t1 should have been evicted once a 3rd trace came in (max 2 kept)
        assert "t1" not in store.list_traces()
        assert set(store.list_traces()) == {"t2", "t3"}
