"""Compatibility contracts for the OpenAI-compatible chat provider."""
from src import runner


def test_gpt5_uses_completion_token_limit_field():
    # GPT-5 rejects the legacy Chat Completions `max_tokens` parameter.
    assert runner.chat_completion_token_limit_field("gpt-5.4") == "max_completion_tokens"


def test_pre_gpt5_uses_legacy_token_limit_field():
    assert runner.chat_completion_token_limit_field("gpt-4.1-nano") == "max_tokens"
