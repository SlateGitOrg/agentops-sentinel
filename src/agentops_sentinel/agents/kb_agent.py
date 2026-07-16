"""Knowledge-base sub-agent: answers "how do I / what is" style tickets."""

from __future__ import annotations

from agentops_sentinel.agents.base import AgentResult
from agentops_sentinel.tools.kb_search import KnowledgeBaseSearchTool


class KnowledgeBaseAgent:
    name = "kb_agent"

    def __init__(self, tool: KnowledgeBaseSearchTool | None = None) -> None:
        self._tool = tool or KnowledgeBaseSearchTool()

    def run(self, ticket_text: str, attempt: int = 1) -> AgentResult:
        del attempt  # KB search has no transient-failure mode; deterministic
        result = self._tool.run(ticket_text)
        if not result.article_id:
            return AgentResult(
                content="No relevant knowledge-base article was found for this ticket.",
                confidence=0.15,
                data={"article_id": None},
            )
        content = f"[{result.article_id}] {result.title}: {result.snippet}"
        return AgentResult(
            content=content,
            confidence=result.score,
            data={"article_id": result.article_id, "title": result.title},
        )
