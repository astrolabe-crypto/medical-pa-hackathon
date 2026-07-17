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

# Spoken when we cannot reach the care team / a live API mid-demo. Pre-synthesised
# to FALLBACK_AUDIO at build time so it needs no network on stage.
FALLBACK_LINE = ("I can't reach your care team right now. "
                 "If this feels urgent, please call 111.")


@dataclass
class Config:
    mode: str                      # "mock" | "live"
    openai_api_key: str | None
    openai_base_url: str
    chat_model: str
    stt_model: str
    tts_model: str
    tts_voice: str
    world_seed: int
    world_timeline: str

    @property
    def live(self) -> bool:
        return self.mode == "live"


def load_config() -> Config:
    mode = os.environ.get("DEMO_MODE", "mock").strip().lower()
    if mode not in ("mock", "live"):
        raise SystemExit(f"DEMO_MODE must be 'mock' or 'live', got {mode!r}")
    key = os.environ.get("OPENAI_API_KEY")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    cfg = Config(
        mode=mode,
        openai_api_key=key,
        openai_base_url=base,
        chat_model=os.environ.get("DEMO_CHAT_MODEL", "gpt-5.4"),
        stt_model=os.environ.get("DEMO_STT_MODEL", "whisper-1"),
        tts_model=os.environ.get("DEMO_TTS_MODEL", "gpt-4o-mini-tts"),
        tts_voice=os.environ.get("DEMO_TTS_VOICE", "shimmer"),
        world_seed=int(os.environ.get("DEMO_WORLD_SEED", "1234")),
        world_timeline=os.environ.get("DEMO_TIMELINE", "hf_decompensation"),
    )
    if cfg.live and not cfg.openai_api_key:
        raise SystemExit(
            "DEMO_MODE=live but OPENAI_API_KEY is not set. "
            "Set the key, or run with DEMO_MODE=mock for the offline demo.")
    return cfg
