# bot/stt.py
"""
Speech-to-text for voice messages using OpenAI Whisper.

Telegram sends voice messages as OGG/OPUS files.
Whisper supports OGG OPUS natively — no conversion needed.
"""

import io
import logging
import os
import random

import httpx

logger = logging.getLogger(__name__)

# Chance the bot reacts to a voice message it wasn't tagged in
VOICE_REACT_CHANCE = float(os.getenv("VOICE_REACT_CHANCE", "0.45"))


async def transcribe_voice(file_url: str) -> str | None:
    """
    Download a Telegram voice file and transcribe it with Whisper.

    Returns the transcribed text, or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(file_url)
            resp.raise_for_status()
            audio_bytes = resp.content
    except Exception as e:
        logger.warning("Voice download failed: %s", e)
        return None

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI()

        # Whisper requires a file-like object with a name hint for format detection
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "voice.ogg"

        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            # Hint: mostly Azerbaijani but mix of az/ru/en is common
            language=None,  # auto-detect
        )
        text = response.text.strip()
        return text if text else None

    except Exception as e:
        logger.warning("Whisper transcription failed: %s", e)
        return None


def should_react_to_voice(mentioned: bool = False) -> bool:
    """Decide whether to react to a voice message."""
    if mentioned:
        return True
    return random.random() < VOICE_REACT_CHANCE
