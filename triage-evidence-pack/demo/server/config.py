"""Env-driven config for the voice-loop demo. Nothing hardcoded; fail loud
and clear at startup if live mode lacks a key."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent.parent          # .../demo
REPO_ROOT = DEMO_DIR.parent                                # .../triage-evidence-pack
STATIC_DIR = DEMO_DIR / "static"
NURSE_DIR = DEMO_DIR / "nurse"                             # Piece 4 care-team view
EVIDENCE_DIR = DEMO_DIR / "evidence"                       # Piece 5 evidence reveal
RESULTS_DIR = REPO_ROOT / "results"                        # Gate 0 run artifacts
REPLAYS_DIR = DEMO_DIR / "replays"
ESCALATIONS_LOG = DEMO_DIR / "escalations.jsonl"
MARGARET_YAML = DEMO_DIR / "margaret.yaml"
MARGARET_STATE = DEMO_DIR / "world" / "margaret_state.yaml"   # engine-owned, git-ignored
FALLBACK_AUDIO = REPLAYS_DIR / "_fallback_unreachable.mp3"
TTS_CACHE_DIR = REPLAYS_DIR / "tts-cache"

# Spoken when we cannot reach the care team / a live API mid-demo. Pre-synthesised
# to FALLBACK_AUDIO at build time so it needs no network on stage.
FALLBACK_LINE = ("I can't reach your care team right now. "
                 "If this feels urgent, please call one one one.")


def _load_project_env() -> None:
    """Load the local project .env without overriding an explicitly exported value.

    The macOS launcher is started by Finder/Terminal, which does not inherit
    values from a developer's shell.  Keeping this tiny parser here makes the
    documented .env setup work for the demo while leaving system environment
    variables authoritative.  It intentionally supports only ordinary
    KEY=value lines; secrets are never logged.
    """
    path = REPO_ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


@dataclass
class Config:
    mode: str                      # "mock" | "live"
    llm_provider: str              # "openai" | "anthropic"
    openai_api_key: str | None
    openai_base_url: str
    anthropic_api_key: str | None
    anthropic_base_url: str
    chat_model: str
    stt_provider: str              # "openai" | "elevenlabs"
    stt_model: str
    tts_model: str
    tts_voice: str
    tts_provider: str              # "openai" | "elevenlabs" | "browser"
    elevenlabs_api_key: str | None
    elevenlabs_voice_id: str | None
    elevenlabs_model: str
    world_seed: int
    world_timeline: str

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @property
    def llm_api_key(self) -> str | None:
        return self.anthropic_api_key if self.llm_provider == "anthropic" else self.openai_api_key

    @property
    def llm_base_url(self) -> str:
        return self.anthropic_base_url if self.llm_provider == "anthropic" else self.openai_base_url

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def stt_ready(self) -> bool:
        if self.stt_provider == "elevenlabs":
            return bool(self.elevenlabs_api_key)
        return bool(self.openai_api_key)

    @property
    def live_ready(self) -> bool:
        return self.live and self.llm_ready and self.stt_ready

    @property
    def tts_enabled(self) -> bool:
        """Whether the server can provide a high-quality voice right now."""
        if self.tts_provider == "elevenlabs":
            return bool(self.elevenlabs_api_key and self.elevenlabs_voice_id)
        return self.tts_provider == "openai" and self.live and bool(self.openai_api_key)


def load_config() -> Config:
    _load_project_env()
    mode = os.environ.get("DEMO_MODE", "mock").strip().lower()
    if mode not in ("mock", "live"):
        raise SystemExit(f"DEMO_MODE must be 'mock' or 'live', got {mode!r}")
    key = os.environ.get("OPENAI_API_KEY")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    anthropic_base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    llm_provider = os.environ.get(
        "DEMO_LLM_PROVIDER", "anthropic" if anthropic_key else "openai").strip().lower()
    if llm_provider not in ("openai", "anthropic"):
        raise SystemExit("DEMO_LLM_PROVIDER must be 'openai' or 'anthropic'.")
    stt_provider = os.environ.get(
        "DEMO_STT_PROVIDER", "elevenlabs" if os.environ.get("ELEVENLABS_API_KEY") else "openai").strip().lower()
    if stt_provider not in ("openai", "elevenlabs"):
        raise SystemExit("DEMO_STT_PROVIDER must be 'openai' or 'elevenlabs'.")
    tts_provider = os.environ.get("DEMO_TTS_PROVIDER", "openai").strip().lower()
    if tts_provider not in ("openai", "elevenlabs", "browser"):
        raise SystemExit("DEMO_TTS_PROVIDER must be 'openai', 'elevenlabs', or 'browser'.")
    cfg = Config(
        mode=mode,
        llm_provider=llm_provider,
        openai_api_key=key,
        openai_base_url=base,
        anthropic_api_key=anthropic_key,
        anthropic_base_url=anthropic_base,
        chat_model=os.environ.get(
            "DEMO_CHAT_MODEL", "claude-haiku-4-5" if llm_provider == "anthropic" else "gpt-5.4"),
        stt_provider=stt_provider,
        stt_model=os.environ.get("DEMO_STT_MODEL", "scribe_v2" if stt_provider == "elevenlabs" else "whisper-1"),
        tts_model=os.environ.get("DEMO_TTS_MODEL", "gpt-4o-mini-tts"),
        tts_voice=os.environ.get("DEMO_TTS_VOICE", "shimmer"),
        tts_provider=tts_provider,
        elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY"),
        elevenlabs_voice_id=os.environ.get("ELEVENLABS_VOICE_ID"),
        elevenlabs_model=os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
        world_seed=int(os.environ.get("DEMO_WORLD_SEED", "1234")),
        world_timeline=os.environ.get("DEMO_TIMELINE", "hf_decompensation"),
    )
    if cfg.live and not cfg.llm_ready:
        raise SystemExit(
            f"DEMO_MODE=live but the {cfg.llm_provider} API key is not set. "
            "Set the key, or run with DEMO_MODE=mock for the offline demo.")
    if cfg.live and not cfg.stt_ready:
        raise SystemExit(
            f"DEMO_MODE=live but the {cfg.stt_provider} STT key is not set.")
    return cfg
