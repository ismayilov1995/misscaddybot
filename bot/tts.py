# bot/tts.py
"""
Text-to-Speech via OpenAI TTS (tts-1-hd).

Generates MP3 audio suitable for Telegram voice messages.
Uses OpenAI's neural TTS which handles mixed Azerbaijani/English/technical
text naturally — code-switching (az + en terms) sounds human, not robotic.

Voice is auto-selected based on persona gender:
  [Qadın] bio → nova  (warm, natural female)
  [Kişi]  bio → onyx  (deep, confident male)
  Override with TTS_VOICE env var.

Speed is slightly randomized per message for natural variation.

Falls back to Edge TTS if OpenAI call fails.

Env vars:
  TTS_VOICE    — Override voice name. Default: auto-detect from persona gender
  VOICE_CHANCE — Probability of sending voice (0.0–1.0). Default: 0.08
"""

import io
import logging
import os
import random

logger = logging.getLogger(__name__)

VOICE_CHANCE = float(os.getenv("VOICE_CHANCE", "0.08"))

# OpenAI voice names
_VOICE_FEMALE = "nova"   # warm, natural
_VOICE_MALE = "onyx"     # deep, confident

# Edge TTS fallback voices
_EDGE_FEMALE = "az-AZ-BanuNeural"
_EDGE_MALE = "az-AZ-BabekNeural"


def should_send_voice(persona_voice_chance: int | None = None) -> bool:
    """
    Return True with the given probability.

    persona_voice_chance: percentage (0-100) from persona DB field.
    Falls back to VOICE_CHANCE env var if not provided.
    """
    if persona_voice_chance is not None:
        return random.random() < (persona_voice_chance / 100.0)
    return random.random() < VOICE_CHANCE


def _pick_voice(persona_bio: str = "") -> str:
    """
    Pick OpenAI TTS voice based on persona gender.

    Checks for [Kişi] or [Qadın] prefix in bio (set by dashboard).
    Falls back to TTS_VOICE env var, then female default.
    """
    override = os.getenv("TTS_VOICE")
    if override:
        return override

    bio_lower = persona_bio.lower()
    if bio_lower.startswith("[kişi]") or bio_lower.startswith("[kisi]"):
        return _VOICE_MALE

    # Default: female (covers [Qadın] and unset)
    return _VOICE_FEMALE


def _pick_edge_voice(persona_bio: str = "") -> str:
    """Pick Edge TTS fallback voice based on persona gender."""
    bio_lower = persona_bio.lower()
    if bio_lower.startswith("[kişi]") or bio_lower.startswith("[kisi]"):
        return _EDGE_MALE
    return _EDGE_FEMALE


async def text_to_voice(text: str, persona_bio: str = "") -> io.BytesIO | None:
    """
    Convert text to audio using OpenAI TTS (tts-1-hd).

    Falls back to Edge TTS if OpenAI fails.
    Returns a BytesIO buffer ready for Telegram send_voice, or None on error.
    Speed is slightly randomized per call for natural feel.
    """
    voice = _pick_voice(persona_bio)
    # Subtle speed variation: slightly slower or faster each time
    speed = round(random.uniform(0.92, 1.08), 2)

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI()

        response = await client.audio.speech.create(
            model="tts-1-hd",
            voice=voice,
            input=text,
            speed=speed,
            response_format="mp3",
        )

        buffer = io.BytesIO(response.content)
        buffer.name = "voice.mp3"
        buffer.seek(0)
        logger.debug("OpenAI TTS: voice=%s speed=%.2f len=%d", voice, speed, len(response.content))
        return buffer

    except Exception as e:
        logger.warning("OpenAI TTS failed (voice=%s): %s — trying Edge TTS fallback", voice, e)
        return await _edge_tts_fallback(text, persona_bio)


async def _edge_tts_fallback(text: str, persona_bio: str = "") -> io.BytesIO | None:
    """Edge TTS fallback when OpenAI TTS is unavailable."""
    try:
        import tempfile
        import edge_tts

        edge_voice = _pick_edge_voice(persona_bio)
        communicate = edge_tts.Communicate(text, edge_voice)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
            await communicate.save(tmp.name)
            tmp.seek(0)
            data = tmp.read()

        if not data:
            return None

        buffer = io.BytesIO(data)
        buffer.name = "voice.mp3"
        buffer.seek(0)
        logger.info("Edge TTS fallback succeeded (voice=%s)", edge_voice)
        return buffer

    except Exception as e:
        logger.warning("Edge TTS fallback also failed: %s", e)
        return None
