"""Unit tests for the deterministic offline LLM reasoner and factory."""

from __future__ import annotations

from agentops_sentinel.agents.supervisor import ROUTES
from agentops_sentinel.config import Settings
from agentops_sentinel.llm import FakeLLMClient, build_llm_client


class TestFakeLLMRouting:
    def setup_method(self):
        self.llm = FakeLLMClient()

    def test_kb_style_ticket_routes_to_kb_agent(self):
        decision = self.llm.decide(
            system_prompt="route",
            user_prompt="How do I configure SSO integration for my team?",
            choices=ROUTES,
        )
        assert decision.choice == "kb_agent"
        assert 0 <= decision.confidence <= 1

    def test_order_style_ticket_routes_to_order_agent(self):
        decision = self.llm.decide(
            system_prompt="route",
            user_prompt="Where is my order? The tracking shows no shipment update.",
            choices=ROUTES,
        )
        assert decision.choice == "order_agent"

    def test_refund_style_ticket_routes_to_refund_agent(self):
        decision = self.llm.decide(
            system_prompt="route",
            user_prompt="I want a refund for order ORD-1002, please reimburse me.",
            choices=ROUTES,
        )
        assert decision.choice == "refund_agent"

    def test_hostile_ticket_routes_to_escalate(self):
        decision = self.llm.decide(
            system_prompt="route",
            user_prompt="This is fraud, unacceptable, get me a lawyer now.",
            choices=ROUTES,
        )
        assert decision.choice == "escalate"

    def test_ambiguous_ticket_falls_back_gracefully(self):
        decision = self.llm.decide(system_prompt="route", user_prompt="hello", choices=ROUTES)
        assert decision.choice in ROUTES
        assert decision.confidence == 0.5


class TestFakeLLMCritique:
    def setup_method(self):
        self.llm = FakeLLMClient()

    def test_high_confidence_result_is_accepted(self):
        decision = self.llm.decide(
            system_prompt="critique",
            user_prompt="observed_confidence=0.95\nattempt=1\ntool_error=false\nmax_retries=2",
            choices=["accept", "retry", "escalate"],
        )
        assert decision.choice == "accept"

    def test_low_confidence_first_attempt_retries(self):
        decision = self.llm.decide(
            system_prompt="critique",
            user_prompt="observed_confidence=0.2\nattempt=1\ntool_error=false\nmax_retries=2",
            choices=["accept", "retry", "escalate"],
        )
        assert decision.choice == "retry"

    def test_tool_error_first_attempt_retries(self):
        decision = self.llm.decide(
            system_prompt="critique",
            user_prompt="observed_confidence=0.0\nattempt=1\ntool_error=true\nmax_retries=2",
            choices=["accept", "retry", "escalate"],
        )
        assert decision.choice == "retry"

    def test_tool_error_with_no_retry_choice_escalates(self):
        decision = self.llm.decide(
            system_prompt="critique",
            user_prompt="observed_confidence=0.0\nattempt=3\ntool_error=true\nmax_retries=2",
            choices=["accept", "escalate"],
        )
        assert decision.choice == "escalate"

    def test_low_confidence_with_no_retry_choice_escalates(self):
        decision = self.llm.decide(
            system_prompt="critique",
            user_prompt="observed_confidence=0.2\nattempt=3\ntool_error=false\nmax_retries=2",
            choices=["accept", "escalate"],
        )
        assert decision.choice == "escalate"


class TestBuildLLMClient:
    def test_defaults_to_fake_client(self, monkeypatch):
        monkeypatch.delenv("AGENTOPS_LLM_PROVIDER", raising=False)
        settings = Settings.load()
        client = build_llm_client(settings)
        assert isinstance(client, FakeLLMClient)

    def test_anthropic_without_api_key_falls_back_to_fake(self, monkeypatch):
        monkeypatch.setenv("AGENTOPS_LLM_PROVIDER", "anthropic")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        settings = Settings.load()
        client = build_llm_client(settings)
        assert isinstance(client, FakeLLMClient)

    def test_openai_without_api_key_falls_back_to_fake(self, monkeypatch):
        monkeypatch.setenv("AGENTOPS_LLM_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        settings = Settings.load()
        client = build_llm_client(settings)
        assert isinstance(client, FakeLLMClient)
