# bot/reactions.py
"""
Passive emoji reactions — makes the bot feel alive without replying.

Real people constantly react to messages (👍, 😂, 🔥) without typing.
This is the #1 signal that separates a human from a bot in group chats.
"""

import asyncio
import logging
import os
import random

from telegram import ReactionTypeEmoji

logger = logging.getLogger(__name__)

# Base probability of reacting to any message (12%)
REACTION_CHANCE = float(os.getenv("REACTION_CHANCE", "0.12"))

# ── keyword → emoji mappings ──────────────────────────────────────────

_FUNNY = {"haha", "lol", "🤣", "😂", "pəh", "zarafat", "gülməli", "ay gülürəm",
          "ahaha", "hahah", "lmao", "ahahah", "sdfg", "dksjf", "ohoho"}

_COOL = {"əla", "super", "gözəl", "maraqlı", "vay", "wow", "kruto",
         "ura", "class", "bomba", "möhtəşəm", "mükəmməl"}

_SAD = {"heyif", "pis", "bezdim", "yoruldum", "sıxıldım", "kədərli",
        "ağlayıram", "😢", "😭", "dərd"}

_LOVE = {"sevgi", "canım", "əzizim", "❤️", "😍", "gözəlsən", "sevirəm",
         "can", "balam"}

_AGREE = {"doğrudu", "razıyam", "düz deyirsən", "həə", "bəli", "100%",
          "aynen", "dəqiq", "elə", "hə"}

# Telegram-allowed reaction emoji (Bot API subset)
_GENERAL = ["👍", "👀", "😂", "🔥", "❤️", "🤔", "👏", "💯"]


def pick_reaction(text: str) -> str:
    """Pick a contextually appropriate emoji for a message."""
    lower = text.lower()

    if any(w in lower for w in _FUNNY):
        return random.choice(["😂", "🤣", "😁", "💯"])
    if any(w in lower for w in _COOL):
        return random.choice(["🔥", "👏", "💯", "🤩"])
    if any(w in lower for w in _SAD):
        return random.choice(["😢", "❤️"])
    if any(w in lower for w in _LOVE):
        return random.choice(["❤️", "😍", "🥰"])
    if any(w in lower for w in _AGREE):
        return random.choice(["👍", "💯", "🤝"])
    if "?" in text:
        return random.choice(["🤔", "👀"])

    return random.choice(_GENERAL)


async def maybe_react(
    bot,
    chat_id: int,
    message_id: int,
    text: str,
    *,
    chance_override: float | None = None,
) -> bool:
    """
    Possibly react to a message with an emoji.

    Called on every incoming message (not just mentions).
    Returns True if a reaction was sent.
    """
    chance = chance_override if chance_override is not None else REACTION_CHANCE
    if random.random() > chance:
        return False

    emoji = pick_reaction(text)

    try:
        # Small delay — real people don't react instantly
        await asyncio.sleep(random.uniform(0.5, 3.0))

        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
        logger.debug("Reacted with %s to msg %d in chat %d", emoji, message_id, chat_id)
        return True
    except Exception as e:
        # Reaction API might not be available in all group types
        logger.debug("Reaction failed (chat %d): %s", chat_id, e)
        return False
