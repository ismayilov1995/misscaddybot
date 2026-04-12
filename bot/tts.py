# bot/tts.py
"""
Text-to-Speech via OpenAI TTS API.

Generates OGG/OPUS audio suitable for Telegram voice messages.
Uses OPENAI_API_KEY (same key used for embeddings).

Env vars:
  TTS_MODEL   — "tts-1" (fast/cheap) or "tts-1-hd" (quality). Default: tts-1
  TTS_VOICE   — alloy, echo, fable, onyx, nova, shimmer. Default: nova
  VOICE_CHANCE — probability of sending voice instead of text (0.0–1.0). Default: 0.15
"""

import io
import logging
import os
import random

logger = logging.getLogger(__name__)

TTS_MODEL = os.getenv("TTS_MODEL", "tts-1")
TTS_VOICE = os.getenv("TTS_VOICE", "nova")
VOICE_CHANCE = float(os.getenv("VOICE_CHANCE", "0.15"))


def should_send_voice() -> bool:
    """Return True with VOICE_CHANCE probability."""
    return random.random() < VOICE_CHANCE


async def text_to_voice(text: str) -> io.BytesIO | None:
    """
    Convert text to OGG/OPUS audio using OpenAI TTS.

    Returns a BytesIO buffer ready for Telegram send_voice, or None on error.
    The buffer's name is set to 'voice.ogg' for Telegram compatibility.
    """
    try:
        import openai
    except ImportError:
        logger.error("openai package not installed — cannot generate voice")
        return None

    # Use OPENAI_API_KEY (same as embedding provider)
    client = openai.AsyncOpenAI()

    try:
        response = await client.audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=text,
            response_format="opus",
        )

        buffer = io.BytesIO(response.content)
        buffer.name = "voice.ogg"
        buffer.seek(0)
        return buffer

    except Exception as e:
        logger.warning("TTS generation failed: %s", e)
        return None
