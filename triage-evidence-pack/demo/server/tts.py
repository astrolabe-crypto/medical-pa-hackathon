"""OpenAI TTS wrapper. Streams mp3 chunks to the client so playback can start
on the first chunk. Also a prebuild CLI to synthesise the offline fallback line
once at build time (so wifi-drop needs no network on stage).

    python -m demo.server.tts --prebuild      # writes replays/_fallback_unreachable.mp3
"""
from __future__ import annotations

from typing import AsyncIterator

import httpx

from . import config as demo_config


async def stream_mp3(text: str, cfg: demo_config.Config) -> AsyncIterator[bytes]:
    """Yield mp3 bytes as they arrive from the TTS endpoint."""
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
    if not cfg.openai_api_key:
        raise SystemExit("Prebuild needs OPENAI_API_KEY (run once with a key). "
                         "This synthesises the offline fallback line and the canned "
                         "proactive lines so the demo needs no network for the "
                         "wifi-drop safety net and the offline proactive beat.")
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


if __name__ == "__main__":
    import sys
    if "--prebuild" in sys.argv:
        _prebuild()
    else:
        print(__doc__)
