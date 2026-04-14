# bot/vision.py
"""
Vision: understand images/photos sent in the group.

Uses GPT-4o or Grok vision to describe images in context,
then generates a natural persona reply — just like a real person
who sees the photo and reacts.
"""

import base64
import logging
import os
import random

import httpx

logger = logging.getLogger(__name__)

# Chance to reply to a photo (not every photo needs a comment)
VISION_REPLY_CHANCE = float(os.getenv("VISION_REPLY_CHANCE", "0.60"))


async def _download_photo(file_url: str) -> bytes | None:
    """Download a Telegram file URL and return raw bytes."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(file_url)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.warning("Photo download failed: %s", e)
        return None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


async def describe_and_reply(
    photo_bytes: bytes,
    persona_name: str,
    persona_bio: str,
    persona_personality: str,
    sender_name: str,
    caption: str | None,
    recent_context: list[dict],
) -> str | None:
    """
    Send photo + persona context to a vision model and get a natural reply.

    Tries GPT-4o first (best vision), falls back to Grok vision.
    Returns reply text or None.
    """
    provider = os.getenv("AI_PROVIDER", "openai").lower()

    # Build the persona instruction
    caption_line = f'Şəklin yazısı: "{caption}"' if caption else "Şəklin yazısı yoxdur."
    recent_lines = "\n".join(
        f"{'Bot' if m['role'] == 'assistant' else sender_name}: {m['content'][-120:]}"
        for m in recent_context[-4:]
    )

    system = (
        f"Sən {persona_name}san. {persona_bio}\n"
        f"{persona_personality}\n\n"
        "Qrup söhbətindəsən. Kimsə şəkil paylaşdı. "
        "Şəklə bax və real insan kimi qısa, təbii reaksiya ver. "
        "Siyahı yox, rəsmi dil yox — just normal qrup yazışması. "
        "1-2 cümlə kifayətdir. Bəzən sual soruş, bəzən yorum et, bəzən zarafat et."
    )

    user_text = (
        f"{sender_name} şəkil paylaşdı. {caption_line}\n"
        f"Son söhbət:\n{recent_lines}\n\n"
        "Bu şəklə nə deyərsən?"
    )

    # Try GPT-4o vision (best quality)
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        reply = await _vision_openai(photo_bytes, system, user_text, openai_key)
        if reply:
            return reply

    # Fallback: Grok vision
    xai_key = os.getenv("XAI_API_KEY")
    if xai_key:
        reply = await _vision_grok(photo_bytes, system, user_text, xai_key)
        if reply:
            return reply

    logger.warning("No vision-capable provider available (need OPENAI_API_KEY or XAI_API_KEY)")
    return None


async def _vision_openai(
    photo_bytes: bytes,
    system: str,
    user_text: str,
    api_key: str,
) -> str | None:
    try:
        import openai
        client = openai.AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o",
            max_tokens=200,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{_b64(photo_bytes)}",
                                "detail": "low",
                            },
                        },
                    ],
                },
            ],
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.warning("GPT-4o vision failed: %s", e)
        return None


async def _vision_grok(
    photo_bytes: bytes,
    system: str,
    user_text: str,
    api_key: str,
) -> str | None:
    try:
        import openai
        client = openai.AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        resp = await client.chat.completions.create(
            model="grok-2-vision-latest",
            max_tokens=200,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{_b64(photo_bytes)}",
                            },
                        },
                    ],
                },
            ],
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.warning("Grok vision failed: %s", e)
        return None


def should_react_to_photo(chance_override: float | None = None) -> bool:
    chance = chance_override if chance_override is not None else VISION_REPLY_CHANCE
    return random.random() < chance
