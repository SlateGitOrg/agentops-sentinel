"""Knowledge-base search tool.

A tiny bundled article store with a keyword-overlap scorer. This
deliberately avoids embeddings/vector DBs (which would need a model
download or network call) while still doing genuine relevance ranking
over real text, so the KB sub-agent's behavior is meaningful rather
than a lookup table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ARTICLES: list[dict[str, str]] = [
    {
        "id": "KB-100",
        "title": "How to configure API rate limits",
        "body": (
            "To configure API rate limits, open Settings > API and set the "
            "requests-per-minute cap. Error code 429 means you exceeded it. "
            "Contact support if you need a higher limit for your plan."
        ),
    },
    {
        "id": "KB-101",
        "title": "Setting up SSO integration",
        "body": (
            "SSO integration is configured under Settings > Security > SSO. "
            "Upload your identity provider's metadata XML and map the email "
            "claim. See our docs for SAML setup and troubleshooting."
        ),
    },
    {
        "id": "KB-102",
        "title": "Understanding error code 500",
        "body": (
            "Error code 500 indicates an internal server error. Retry the "
            "request; if it persists, check our status page or contact "
            "support with the request ID from the response headers."
        ),
    },
    {
        "id": "KB-103",
        "title": "How to reset your password",
        "body": (
            "To reset your password, click 'Forgot password' on the login "
            "page. A reset link is emailed to your account address and "
            "expires after one hour."
        ),
    },
    {
        "id": "KB-104",
        "title": "Webhook signature verification FAQ",
        "body": (
            "Webhook payloads are signed with HMAC-SHA256. Verify the "
            "'X-Signature' header against your webhook secret before "
            "processing the payload to prevent spoofed events."
        ),
    },
    {
        "id": "KB-105",
        "title": "What is the difference between plans",
        "body": (
            "The Starter plan includes 3 seats and community support. "
            "The Pro plan adds SSO, higher rate limits, and priority "
            "support. Enterprise adds a dedicated account manager."
        ),
    },
]

_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "to",
    "of",
    "and",
    "for",
    "in",
    "on",
    "how",
    "do",
    "i",
    "my",
    "what",
    "it",
}


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


@dataclass
class KBSearchResult:
    article_id: str
    title: str
    snippet: str
    score: float  # 0..1, overlap-based relevance


class KnowledgeBaseSearchTool:
    """Searches the bundled article store and ranks by token overlap."""

    name = "kb_search"

    def __init__(self, articles: list[dict[str, str]] | None = None) -> None:
        self._articles = articles if articles is not None else _ARTICLES

    def run(self, query: str) -> KBSearchResult:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return KBSearchResult(article_id="", title="", snippet="", score=0.0)

        best: KBSearchResult | None = None
        for article in self._articles:
            article_tokens = _tokenize(article["title"] + " " + article["body"])
            overlap = query_tokens & article_tokens
            if not overlap:
                continue
            score = len(overlap) / len(query_tokens)
            score = min(1.0, score)
            if best is None or score > best.score:
                snippet = article["body"][:160].rsplit(" ", 1)[0] + "…"
                best = KBSearchResult(
                    article_id=article["id"], title=article["title"], snippet=snippet, score=score
                )
        return best if best is not None else KBSearchResult("", "", "", 0.0)
