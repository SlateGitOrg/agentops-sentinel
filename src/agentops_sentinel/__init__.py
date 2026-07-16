"""agentops-sentinel: reliable, observable, cost-bounded agentic workflows.

A supervisor/planner agent delegates support tickets to specialized
tool-using sub-agents (knowledge-base search, order lookup, refund
processing). Every decision and tool call is traced with OpenTelemetry,
a self-critique loop retries weak results under a bounded step and
dollar budget, and guardrails escalate to a human when the agent can't
finish confidently, safely, or affordably.
"""

__version__ = "0.1.0"
