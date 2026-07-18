"""Provider selection is explicit: live Anthropic + ElevenLabs needs no OpenAI key."""
from __future__ import annotations

from demo.server.config import load_config


def test_anthropic_elevenlabs_live_configuration(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "live")
    monkeypatch.setenv("DEMO_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("DEMO_STT_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-eleven")
    monkeypatch.delenv("DEMO_CHAT_MODEL", raising=False)
    monkeypatch.delenv("DEMO_STT_MODEL", raising=False)
    cfg = load_config()
    assert cfg.llm_provider == "anthropic"
    assert cfg.stt_provider == "elevenlabs"
    assert cfg.chat_model == "claude-haiku-4-5"
    assert cfg.stt_model == "scribe_v2"
    assert cfg.live_ready
