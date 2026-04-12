# bot/tts.py
"""
Text-to-Speech via Microsoft Edge TTS.

Generates MP3 audio suitable for Telegram voice messages.
Free — no API key required. Native Azerbaijani voices.

Env vars:
  TTS_VOICE    — Edge TTS voice name. Default: az-AZ-BanuNeural (Azerbaijani female)
                 Other options: az-AZ-BabekNeural (male), or any Edge TTS voice
  VOICE_CHANCE — probability of sending voice instead of text (0.0–1.0). Default: 0.08
"""

import io
import logging
import os
import random
import tempfile

logger = logging.getLogger(__name__)

TTS_VOICE = os.getenv("TTS_VOICE", "az-AZ-BanuNeural")
VOICE_CHANCE = float(os.getenv("VOICE_CHANCE", "0.08"))


def should_send_voice() -> bool:
    """Return True with VOICE_CHANCE probability."""
    return random.random() < VOICE_CHANCE


async def text_to_voice(text: str) -> io.BytesIO | None:
    """
    Convert text to audio using Edge TTS (Microsoft).

    Returns a BytesIO buffer ready for Telegram send_voice, or None on error.
    """
    try:
        import edge_tts
    except ImportError:
        logger.error("edge-tts package not installed — run: pip install edge-tts")
        return None

    try:
        communicate = edge_tts.Communicate(text, TTS_VOICE)

        # edge-tts writes to a file, so use a temp file then read into buffer
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
        logger.warning("TTS generation failed: %s", e)
        return None
