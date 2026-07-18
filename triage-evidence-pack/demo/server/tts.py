"""TTS wrapper. Streams mp3 chunks to the client so playback can start
on the first chunk. Also a prebuild CLI to synthesise the offline fallback line
once at build time (so wifi-drop needs no network on stage).

    python -m demo.server.tts --prebuild      # writes replays/_fallback_unreachable.mp3
"""
from __future__ import annotations

import hashlib
from typing import AsyncIterator

import httpx

from . import config as demo_config


async def _stream_openai_mp3(text: str, cfg: demo_config.Config) -> AsyncIterator[bytes]:
    url = f"{cfg.openai_base_url}/audio/speech"
    payload = {"model": cfg.tts_model, "voice": cfg.tts_voice,
               "input": text, "response_format": "mp3"}
    headers = {"Authorization": f"Bearer {cfg.openai_api_key}",
               "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise RuntimeError(f"tts {resp.status_code}: {body[:160]!r}")
            async for chunk in resp.aiter_bytes():
                if chunk:
                    yield chunk


async def _stream_elevenlabs_mp3(text: str, cfg: demo_config.Config) -> AsyncIterator[bytes]:
    """Stream a licensed ElevenLabs voice without exposing its key to the browser."""
    if not cfg.elevenlabs_api_key or not cfg.elevenlabs_voice_id:
        raise RuntimeError("ElevenLabs TTS needs ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID")
    url = ("https://api.elevenlabs.io/v1/text-to-speech/"
           f"{cfg.elevenlabs_voice_id}?output_format=mp3_44100_128")
    payload = {
        "text": text,
        "model_id": cfg.elevenlabs_model,
        "voice_settings": {"stability": 0.55, "similarity_boost": 0.75},
    }
    headers = {"xi-api-key": cfg.elevenlabs_api_key, "Accept": "audio/mpeg"}
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise RuntimeError(f"ElevenLabs TTS {resp.status_code}: {body[:160]!r}")
            async for chunk in resp.aiter_bytes():
                if chunk:
                    yield chunk


async def stream_mp3(text: str, cfg: demo_config.Config) -> AsyncIterator[bytes]:
    """Yield MP3 bytes from the configured server-side provider."""
    if cfg.tts_provider == "elevenlabs":
        # Cache complete clips.  The same presentation lines then keep their
        # high-quality voice when the venue Wi-Fi disappears; an incomplete
        # request is never cached.
        signature = "|".join((cfg.elevenlabs_voice_id or "", cfg.elevenlabs_model, text))
        path = demo_config.TTS_CACHE_DIR / (hashlib.sha256(signature.encode()).hexdigest() + ".mp3")
        if path.exists() and path.stat().st_size:
            with open(path, "rb") as f:
                while chunk := f.read(64 * 1024):
                    yield chunk
            return
        parts: list[bytes] = []
        async for chunk in _stream_elevenlabs_mp3(text, cfg):
            parts.append(chunk)
            yield chunk
        if parts:
            demo_config.TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"".join(parts))
        return
    if cfg.tts_provider == "openai":
        async for chunk in _stream_openai_mp3(text, cfg):
            yield chunk
        return
    raise RuntimeError("Server TTS is disabled; use the browser fallback.")


async def synth_to_file(text: str, cfg: demo_config.Config, path) -> None:
    with open(path, "wb") as f:
        async for chunk in stream_mp3(text, cfg):
            f.write(chunk)


def proactive_audio_path(rule_id: str):
    return demo_config.REPLAYS_DIR / f"_proactive_{rule_id}.mp3"


def _prebuild() -> None:
    import asyncio
    from .router_adapter import PROACTIVE_CANNED
    cfg = demo_config.load_config()
    if not cfg.tts_enabled:
        raise SystemExit("Prebuild needs a configured TTS provider and key. "
                         "For ElevenLabs set DEMO_TTS_PROVIDER=elevenlabs, "
                         "ELEVENLABS_API_KEY, and ELEVENLABS_VOICE_ID in .env.")
    demo_config.REPLAYS_DIR.mkdir(parents=True, exist_ok=True)

    async def run():
        print(f"Synthesising fallback line -> {demo_config.FALLBACK_AUDIO}")
        await synth_to_file(demo_config.FALLBACK_LINE, cfg, demo_config.FALLBACK_AUDIO)
        for rule_id, line in PROACTIVE_CANNED.items():
            path = proactive_audio_path(rule_id)
            print(f"Synthesising proactive[{rule_id}] -> {path}")
            await synth_to_file(line, cfg, path)
    asyncio.run(run())
    print("done.")


def _prebuild_presentation() -> None:
    """Warm ElevenLabs' local cache for every scripted face response."""
    import asyncio
    from .router_adapter import _CANNED

    cfg = demo_config.load_config()
    if cfg.tts_provider != "elevenlabs" or not cfg.tts_enabled:
        raise SystemExit("Presentation cache needs configured ElevenLabs TTS.")
    lines = list(_CANNED.values()) + [
        "Thank you. Stay sitting upright while you wait for help. Your care team has the important details.",
    ]

    async def run():
        for line in lines:
            print("Caching presentation voice clip...")
            async for _chunk in stream_mp3(line, cfg):
                pass
    asyncio.run(run())
    print(f"done — cached clips are in {demo_config.TTS_CACHE_DIR}")


if __name__ == "__main__":
    import sys
    if "--prebuild-presentation" in sys.argv:
        _prebuild_presentation()
    elif "--prebuild" in sys.argv:
        _prebuild()
    else:
        print(__doc__)
