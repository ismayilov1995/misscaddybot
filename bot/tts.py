# bot/tts.py
"""
Text-to-Speech via Microsoft Edge TTS.

Generates MP3 audio suitable for Telegram voice messages.
Free — no API key required. Native Azerbaijani voices.

Voice is auto-selected based on persona gender:
  [Qadın] bio → az-AZ-BanuNeural (female)
  [Kişi]  bio → az-AZ-BabekNeural (male)
  Override with TTS_VOICE env var.

Prosody is slightly randomized for natural speech — rate and pitch
vary between messages so the bot doesn't sound robotic.

Env vars:
  TTS_VOICE    — Override voice. Default: auto-detect from persona gender
  VOICE_CHANCE — probability of sending voice (0.0–1.0). Default: 0.08
"""

import io
import logging
import os
import random
import tempfile

logger = logging.getLogger(__name__)

VOICE_CHANCE = float(os.getenv("VOICE_CHANCE", "0.08"))

_VOICE_FEMALE = "az-AZ-BanuNeural"
_VOICE_MALE = "az-AZ-BabekNeural"


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
    Pick TTS voice based on persona gender.

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


def _random_prosody() -> tuple[str, str]:
    """
    Return slightly randomized (rate, pitch) for natural variation.

    Rate: -5% to +10% (normal conversational range)
    Pitch: -3Hz to +5Hz (subtle, avoids robotic monotone)
    """
    rate_pct = random.randint(-5, 10)
    rate = f"{rate_pct:+d}%"

    pitch_hz = random.randint(-3, 5)
    pitch = f"{pitch_hz:+d}Hz"

    return rate, pitch


async def text_to_voice(text: str, persona_bio: str = "") -> io.BytesIO | None:
    """
    Convert text to audio using Edge TTS (Microsoft).

    Returns a BytesIO buffer ready for Telegram send_voice, or None on error.
    Prosody (rate/pitch) is slightly randomized per call for natural feel.
    """
    try:
        import edge_tts
    except ImportError:
        logger.error("edge-tts package not installed — run: pip install edge-tts")
        return None

    voice = _pick_voice(persona_bio)
    rate, pitch = _random_prosody()

    try:
        communicate = edge_tts.Communicate(
            text, voice, rate=rate, pitch=pitch
        )

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
            await communicate.save(tmp.name)
            tmp.seek(0)
            data = tmp.read()

        if not data:
            logger.warning("Edge TTS returned empty audio")
            return None

        buffer = io.BytesIO(data)
        buffer.name = "voice.mp3"
        buffer.seek(0)
        return buffer

    except Exception as e:
        logger.warning("TTS generation failed (%s, rate=%s, pitch=%s): %s", voice, rate, pitch, e)
        return None
