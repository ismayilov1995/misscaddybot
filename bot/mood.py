# bot/mood.py
"""
Persistent mood system for the bot persona.

The bot has a current mood that shifts slowly over time (every 3 hours,
20% chance to transition). Mood is stored on the Persona DB record and
injected into the system prompt as a behavioral hint.

Moods: energetic, normal, chill, playful, tired, sarcastic
"""

import logging
import random

logger = logging.getLogger(__name__)

MOODS = ["energetic", "normal", "chill", "playful", "tired", "sarcastic"]

# Smooth transitions — only adjacent moods or stay
_MOOD_ADJACENCY: dict[str, list[str]] = {
    "energetic": ["normal", "playful"],
    "normal":    ["energetic", "chill", "playful"],
    "chill":     ["normal", "tired"],
    "playful":   ["normal", "energetic", "sarcastic"],
    "tired":     ["chill", "normal"],
    "sarcastic": ["playful", "normal"],
}

# Behavioral hints injected into memory_context
_MOOD_HINTS: dict[str, str] = {
    "energetic": (
        "İndi çox enerjilənsən — aktiv, həvəsli yazırsan. "
        "Bəzən ardıcıl 2 cümlə yaza bilərsən, cavabların biraz uzundur."
    ),
    "normal": "",  # no hint needed — default behavior
    "chill": (
        "Bu gün sakit əhvaldasan — rahat, qısa cavablar, tələsmək yoxdur."
    ),
    "playful": (
        "Oyunbaz əhvaldasan — zarafat etmək istəyirsən, şən yazırsan, "
        "bəzən söhbəti uzadırsan."
    ),
    "tired": (
        "Bir az yuxulusan — çox qısa cavablar, bəzən 'hm', 'bilmirəm', "
        "'sonra baxarıq'. Uzun yazmaq istəmirsən."
    ),
    "sarcastic": (
        "Bu gün bir az istehzalısın — zarafatla, yumorla cavab verirsən, "
        "amma qaba olmadan. Bəzən ikimənalı cümlələr işlədirsən."
    ),
}


def get_mood_hint(mood: str) -> str:
    """Return a behavioral hint string for the given mood (empty for 'normal')."""
    return _MOOD_HINTS.get(mood or "normal", "")


def shift_mood(current: str) -> str:
    """
    Potentially transition to a new mood.

    80% chance: stay on current mood.
    20% chance: transition to an adjacent mood.
    """
    if random.random() > 0.20:
        return current  # no change

    adjacent = _MOOD_ADJACENCY.get(current, MOODS)
    new_mood = random.choice(adjacent)
    logger.debug("Mood shift: %s → %s", current, new_mood)
    return new_mood
