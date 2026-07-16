"""OpenTelemetry tracing sidecar.

Every supervisor decision, sub-agent invocation, tool call, and
guardrail trip is emitted as an OTel span. A small in-process exporter
(`DecisionTraceStore`) mirrors finished spans into a compact JSON shape
that the dashboard (and the test suite) can query without needing a
real OTel collector -- there is no network dependency to observe a
trace.

In production you would additionally point this at an OTLP collector
via `configure_tracing(otlp_endpoint=...)`; that path is exercised only
when the endpoint is explicitly configured, so tests never touch the
network.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

_MAX_TICKETS = 500


@dataclass
class DecisionSpan:
    """A flattened, dashboard-friendly view of one traced decision/tool call."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str  # "supervisor" | "agent" | "tool" | "guardrail"
    start_time: float
    end_time: float
    duration_ms: float
    status: str  # "OK" | "ERROR"
    attributes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "kind": self.kind,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 3),
            "status": self.status,
            "attributes": self.attributes,
            "error": self.error,
        }


class DecisionTraceStore:
    """Thread-safe, in-memory store of decision spans keyed by ticket trace_id.

    Bounded to `_MAX_TICKETS` most-recent traces so a long-running
    process (or dashboard demo) doesn't leak memory.
    """

    def __init__(self, max_tickets: int = _MAX_TICKETS) -> None:
        self._lock = threading.Lock()
        self._traces: "deque[str]" = deque(maxlen=max_tickets)
        self._spans: dict[str, list[DecisionSpan]] = defaultdict(list)

    def record(self, span: DecisionSpan) -> None:
        with self._lock:
            if span.trace_id not in self._spans:
                self._traces.append(span.trace_id)
                if len(self._traces) == self._traces.maxlen:
                    # evict spans for the trace that just fell off the deque
                    still_present = set(self._traces)
                    for stale in list(self._spans.keys()):
                        if stale not in still_present:
                            self._spans.pop(stale, None)
            self._spans[span.trace_id].append(span)

    def get_trace(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            spans = sorted(self._spans.get(trace_id, []), key=lambda s: s.start_time)
            return [s.to_dict() for s in spans]

    def list_traces(self) -> list[str]:
        with self._lock:
            return list(self._traces)

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()
            self._spans.clear()


class _DecisionExporter(SpanExporter):
    """OTel SpanExporter that flattens spans into the DecisionTraceStore."""

    def __init__(self, store: DecisionTraceStore) -> None:
        self._store = store

    def export(self, spans: "list[ReadableSpan]") -> SpanExportResult:
        for span in spans:
            ctx = span.get_span_context()
            parent = span.parent
            start = (span.start_time or 0) / 1e9
            end = (span.end_time or span.start_time or 0) / 1e9
            attrs = dict(span.attributes or {})
            kind = str(attrs.get("agentops.kind", "unknown"))
            trace_id_attr = attrs.get("agentops.trace_id")
            trace_id = str(trace_id_attr) if trace_id_attr else format(ctx.trace_id, "032x")
            error = None
            status = "OK"
            if span.status is not None and span.status.status_code == StatusCode.ERROR:
                status = "ERROR"
                error = span.status.description
            self._store.record(
                DecisionSpan(
                    trace_id=trace_id,
                    span_id=format(ctx.span_id, "016x"),
                    parent_span_id=format(parent.span_id, "016x") if parent else None,
                    name=span.name,
                    kind=kind,
                    start_time=start,
                    end_time=end,
                    duration_ms=(end - start) * 1000,
                    status=status,
                    attributes=attrs,
                    error=error,
                )
            )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:  # pragma: no cover - trivial
        return None


# Module-level singletons. `configure_tracing()` (re)builds them; a bare
# import gets a working default so scripts/tests don't need ceremony.
decision_store = DecisionTraceStore()
_tracer_provider: TracerProvider | None = None
_global_provider_registered = False


def configure_tracing(
    service_name: str = "agentops-sentinel",
    console_export: bool = False,
    store: DecisionTraceStore | None = None,
) -> TracerProvider:
    """(Re)configure the tracer provider used by this package.

    Safe to call multiple times (e.g. once per test) -- it always
    installs a fresh provider so traces from one test never leak into
    another. Note that the *global* `opentelemetry.trace` API only
    accepts `set_tracer_provider()` once per process (later calls are a
    silent no-op with a warning) -- so we register with it at most
    once, for the benefit of any external OTel auto-instrumentation,
    but `get_tracer()` below always pulls from our own `_tracer_provider`
    reference rather than the global, so re-configuring per-test works
    correctly regardless of that global-registration restriction.
    """
    global _tracer_provider, decision_store, _global_provider_registered
    if store is not None:
        decision_store = store

    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(_DecisionExporter(decision_store)))

    if console_export:  # pragma: no cover - developer convenience only
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    if not _global_provider_registered:
        trace.set_tracer_provider(provider)
        _global_provider_registered = True

    _tracer_provider = provider
    return provider


def get_tracer(name: str = "agentops_sentinel"):
    if _tracer_provider is None:
        configure_tracing()
    return _tracer_provider.get_tracer(name)


@contextlib.contextmanager
def traced_step(
    name: str,
    *,
    kind: str,
    trace_id: str,
    **attributes: Any,
) -> Iterator[Any]:
    """Context manager wrapping one decision/tool-call as an OTel span.

    Usage::

        with traced_step("kb_agent.search", kind="agent", trace_id=t, query=q) as span:
            result = do_work()
            span.set_attribute("agentops.confidence", result.confidence)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        span.set_attribute("agentops.kind", kind)
        span.set_attribute("agentops.trace_id", trace_id)
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(f"agentops.{key}", value)
        started = time.time()
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:  # re-raised after tracing -- tools/agents decide recovery
            span.set_status(Status(StatusCode.ERROR, description=str(exc)))
            span.set_attribute("agentops.error", str(exc))
            raise
        finally:
            span.set_attribute("agentops.duration_ms", (time.time() - started) * 1000)
