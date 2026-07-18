"""Provider-neutral transcription wrapper (httpx multipart). Sends the recorded
clip (webm/opus from MediaRecorder) as-is; returns a structured result the UI
turns into a spoken retry prompt on failure -- never a stack trace.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

from . import config as demo_config


@dataclass
class STTResult:
    text: Optional[str]
    ok: bool
    error: Optional[str] = None
    latency_ms: float = 0.0


async def transcribe(audio_bytes: bytes, filename: str, cfg: demo_config.Config,
                     content_type: str = "audio/webm") -> STTResult:
    import time
    t0 = time.perf_counter()
    if not audio_bytes:
        return STTResult(None, False, "empty audio")
    files = {"file": (filename or "clip.webm", audio_bytes, content_type)}
    if cfg.stt_provider == "elevenlabs":
        url = "https://api.elevenlabs.io/v1/speech-to-text"
        data = {"model_id": cfg.stt_model, "language_code": "eng"}
        headers = {"xi-api-key": cfg.elevenlabs_api_key or ""}
    else:
        url = f"{cfg.openai_base_url}/audio/transcriptions"
        data = {"model": cfg.stt_model, "language": "en"}
        headers = {"Authorization": f"Bearer {cfg.openai_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, files=files, data=data, headers=headers)
    except Exception as e:
        return STTResult(None, False, f"network: {e}",
                         (time.perf_counter() - t0) * 1000)
    dt = (time.perf_counter() - t0) * 1000
    if resp.status_code >= 400:
        return STTResult(None, False, f"stt {resp.status_code}: {resp.text[:160]}", dt)
    try:
        text = resp.json().get("text", "").strip()
    except Exception as e:
        return STTResult(None, False, f"parse: {e}", dt)
    if not text:
        return STTResult(None, False, "no speech detected", dt)
    return STTResult(text, True, None, dt)
