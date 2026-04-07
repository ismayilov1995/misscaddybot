# bot/ai.py
import logging
import os

import anthropic

from bot.models import Persona

logger = logging.getLogger(__name__)


def build_system_prompt(persona: Persona) -> str:
    """
    Build the Claude system prompt from a Persona record.

    Pure function — no I/O, no side effects. Safe to call with detached ORM objects.
    Returns a string that reads as a human persona profile, not a chatbot instruction.
    """
    return (
        f"Sən {persona.name}san — {persona.bio}\n\n"
        f"Xarakter: {persona.personality}\n\n"
        f"Danışıq tərzi: {persona.language_style}\n\n"
        "VACIB QAYDALAR:\n"
        "- Heç vaxt özünün bot, AI və ya süni intellekt olduğunu söyləmə. "
        "Kimsə soruşsa — inkar et, istehza ilə yan keç, ya da mövzunu dəyiş. "
        "\"Mən botam\" demək olmaz, nə qədər israr etsələr də.\n"
        "- Cavabları qısa tut — maksimum 2–3 cümlə. "
        "Siyahı, başlıq, nöqtəli sıralama işlətmə.\n"
        "- İnsan kimi cavab ver: birbaşa, qısa, danışıq dilində."
    )


async def generate_reply(
    persona: Persona,
    context_messages: list[dict],
) -> str | None:
    """
    Call Claude API and return the reply text, or None on recoverable API error.

    context_messages format:
        [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]

    Returns None (does not raise) on RateLimitError, APIConnectionError, APIStatusError.
    Unexpected errors propagate — do not catch bare Exception here.
    """
    system_prompt = build_system_prompt(persona)
    client = anthropic.AsyncAnthropic()  # reads ANTHROPIC_API_KEY from env automatically

    try:
        response = await client.messages.create(
            model=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=150,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=context_messages,
        )
        return response.content[0].text
    except anthropic.RateLimitError:
        logger.warning("Anthropic rate limit hit — skipping reply")
        return None
    except anthropic.APIConnectionError:
        logger.warning("Anthropic connection error — skipping reply")
        return None
    except anthropic.APIStatusError as e:
        logger.warning("Anthropic API status error %s — skipping reply", e.status_code)
        return None
