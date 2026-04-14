# bot/image_gen.py
"""
Image generation via DALL-E 3.

When someone asks the bot to "draw" or "generate" something, it:
1. Uses GPT to craft an optimized English DALL-E 3 prompt
2. Generates the image
3. Returns raw bytes for Telegram send_photo

Env vars:
  IMAGE_GEN_CHANCE — spontaneous generation probability (default 0.05)
"""

import logging
import os
import random

import httpx

logger = logging.getLogger(__name__)

IMAGE_GEN_CHANCE = float(os.getenv("IMAGE_GEN_CHANCE", "0.05"))

_TRIGGERS = [
    "çək", "cek", "generate", "imagine", "şəkil çək", "sekil cek",
    "draw", "rəsm çək", "resm cek", "foto çək", "photo çək",
    "şəkil göndər", "şəkil at", "göstər şəkil",
]


def should_generate_image(text: str, mentioned: bool = False) -> bool:
    """
    Return True if the message is requesting image generation.

    Trigger keywords always return True.
    Otherwise 5% spontaneous chance when bot is mentioned (very rare).
    """
    lower = text.lower()
    if any(t in lower for t in _TRIGGERS):
        return True
    return mentioned and random.random() < IMAGE_GEN_CHANCE


async def _craft_prompt(user_message: str, persona_personality: str) -> str:
    """
    Use GPT-4o-mini to craft an optimized English DALL-E 3 prompt.

    Falls back to using the user message directly if GPT fails.
    """
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI()
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=150,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You create concise, vivid DALL-E 3 image prompts in English. "
                        "Be specific about style, composition, and mood. Max 200 characters. "
                        "Return ONLY the prompt, no explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Create a DALL-E 3 prompt for this request: '{user_message}'. "
                        f"Persona style hint: {persona_personality[:80]}"
                    ),
                },
            ],
        )
        prompt = resp.choices[0].message.content.strip()
        logger.debug("DALL-E prompt crafted: %s", prompt[:100])
        return prompt
    except Exception as e:
        logger.debug("Prompt crafting failed, using raw message: %s", e)
        return user_message[:400]


async def generate_image(
    user_message: str,
    persona_name: str = "",
    persona_personality: str = "",
) -> bytes | None:
    """
    Generate an image with DALL-E 3 and return raw bytes.

    Returns None on any failure (rate limit, content policy, network error).
    """
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI()

        prompt = await _craft_prompt(user_message, persona_personality)

        response = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )

        image_url = response.data[0].url
        if not image_url:
            return None

        async with httpx.AsyncClient(timeout=30) as http_client:
            img_resp = await http_client.get(image_url)
            img_resp.raise_for_status()
            logger.info("Image generated (%d bytes) for: %s", len(img_resp.content), user_message[:60])
            return img_resp.content

    except Exception as e:
        logger.warning("Image generation failed: %s", e)
        return None
