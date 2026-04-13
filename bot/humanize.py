# bot/humanize.py
"""
Human-like behavior modifiers — makes the bot feel alive.

Features:
  • Message splitting: break long replies into 2-3 short messages
  • Delayed replies: sometimes "miss" a mention and reply later
  • Circadian rhythm: quieter at night, more active during the day
  • Typos: occasional mistakes with self-correction
"""

import random
import re
from datetime import datetime, timezone, timedelta


# ── Message Splitting ─────────────────────────────────────────────────

SPLIT_CHANCE = 0.28  # 28% chance to split long replies

# Short "thinking" prefixes people send before the real message
_PREFILL_MESSAGES = [
    "hə",
    "hə gözlə",
    "bir dəq",
    "aa",
    "hmm",
    "bax",
    "yəni",
    "aha",
]


def maybe_split_reply(text: str) -> list[str]:
    """
    Sometimes split a reply into 2-3 natural messages.

    Returns a list of message parts. If no split, returns [text].
    """
    # Don't split short messages
    if len(text) < 60 or random.random() > SPLIT_CHANCE:
        return [text]

    # Split at sentence boundaries
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    sentences = [s for s in sentences if s.strip()]

    if len(sentences) <= 1:
        return [text]

    # 40% chance: add a short "thinking" prefix before real content
    parts: list[str] = []
    if random.random() < 0.40:
        parts.append(random.choice(_PREFILL_MESSAGES))

    if len(sentences) == 2:
        parts.extend(sentences)
    elif len(sentences) >= 3:
        # Group into 2 or 3 chunks
        if random.random() < 0.5 and len(sentences) >= 4:
            # 3 chunks
            third = len(sentences) // 3
            parts.append(" ".join(sentences[:third]))
            parts.append(" ".join(sentences[third : third * 2]))
            parts.append(" ".join(sentences[third * 2 :]))
        else:
            # 2 chunks
            mid = len(sentences) // 2
            parts.append(" ".join(sentences[:mid]))
            parts.append(" ".join(sentences[mid:]))
    else:
        parts.append(text)

    # Filter empty parts and limit to 4 max
    return [p for p in parts if p.strip()][:4]


# ── Delayed Replies ───────────────────────────────────────────────────

DELAYED_REPLY_CHANCE = 0.07  # 7% chance to "miss" a mention

# Delay range in seconds (5 min to 45 min)
DELAYED_MIN = 300
DELAYED_MAX = 2700

_LATE_PREFIXES = [
    "Bağışla indi gördüm",
    "Hə indi oxudum",
    "Aa bunu qaçırmışdım",
    "Indicə gördüm mesajını",
    "Bağışla məşğul idim",
    "Hə gördüm gördüm",
]


def should_delay_reply() -> tuple[bool, int]:
    """
    Decide if this reply should be delayed.

    Returns (should_delay, delay_seconds).
    Night hours (1-7 AM Baku time) increase delay chance to ~15%.
    """
    baku_hour = _baku_hour()

    # At night, more likely to "miss" messages
    chance = DELAYED_REPLY_CHANCE
    if 1 <= baku_hour <= 7:
        chance = 0.20  # 20% at night

    if random.random() > chance:
        return False, 0

    delay = random.randint(DELAYED_MIN, DELAYED_MAX)
    # Night delays are longer
    if 1 <= baku_hour <= 7:
        delay = random.randint(600, 5400)  # 10 min to 1.5 hours

    return True, delay


def get_late_prefix() -> str:
    """Random 'sorry, just saw this' prefix."""
    return random.choice(_LATE_PREFIXES)


# ── Circadian Rhythm ──────────────────────────────────────────────────

def _baku_hour() -> int:
    """Current hour in Baku timezone (UTC+4)."""
    baku_tz = timezone(timedelta(hours=4))
    return datetime.now(baku_tz).hour


def get_energy_level() -> str:
    """
    Return current energy level based on time of day (Baku time).

    00-06: sleepy — very short replies, might not reply
    07-09: waking — short, casual
    10-14: active — normal to long replies
    15-19: peak — most energetic, longer, more jokes
    20-23: winding — gradually shorter
    """
    hour = _baku_hour()
    if 0 <= hour <= 6:
        return "sleepy"
    if 7 <= hour <= 9:
        return "waking"
    if 10 <= hour <= 14:
        return "active"
    if 15 <= hour <= 19:
        return "peak"
    return "winding"


def adjust_max_tokens(base_min: int = 150, base_max: int = 450) -> int:
    """Adjust reply length based on time of day."""
    energy = get_energy_level()
    if energy == "sleepy":
        return random.randint(40, 120)
    if energy == "waking":
        return random.randint(80, 200)
    if energy == "peak":
        return random.randint(200, 500)
    if energy == "winding":
        return random.randint(100, 300)
    # active
    return random.randint(base_min, base_max)


def get_mood_hint() -> str | None:
    """
    Return a mood hint to append to the system prompt based on time of day.

    Returns None during normal "active" hours (no hint needed).
    """
    energy = get_energy_level()
    if energy == "sleepy":
        return (
            "İndi gecə yarısıdır, sən çox yuxulusan. "
            "Cavabların çox qısa, bəzən bir söz. "
            "Bəzən 'yatıram' de, bəzən sadəcə emoji at. "
            "Qrammatik səhv edə bilərsən — yuxulu danışırsan."
        )
    if energy == "waking":
        return (
            "İndi səhərdir, tazəcə oyandın. "
            "Hələ tam oyanmamısan, cavabların qısa və sakitdir. "
            "Kofe içməyə ehtiyacın var."
        )
    if energy == "winding":
        return (
            "Axşamdır, gün yorucu olub. "
            "Cavabların bir az qısa, amma rahat. "
            "Yuxun gəlir amma hələ yatmırsan."
        )
    return None


# ── Typos & Self-Correction ──────────────────────────────────────────

TYPO_CHANCE = 0.08  # 8% chance to introduce a typo

# Common Azerbaijani keyboard typos (adjacent keys, missed letters)
_TYPO_MAP = {
    "ə": ["e", "a"],
    "ş": ["s", "sh"],
    "ç": ["c"],
    "ö": ["o"],
    "ü": ["u"],
    "ğ": ["g"],
    "ı": ["i", ""],
}

_CORRECTION_FORMATS = [
    "{correct}*",
    "{correct} *",
    "yəni {correct}",
    "{correct} demək istəyirdim",
]


def maybe_add_typo(text: str) -> tuple[str, str | None]:
    """
    Sometimes introduce a typo and return a correction message.

    Returns (modified_text, correction_or_none).
    If no typo, returns (text, None).
    """
    if len(text) < 20 or random.random() > TYPO_CHANCE:
        return text, None

    # Find a word with a replaceable character
    words = text.split()
    if len(words) < 3:
        return text, None

    # Pick a random word (not first, not last — middle is most natural)
    candidates = [(i, w) for i, w in enumerate(words[1:-1], 1)
                  if len(w) > 3 and any(c in _TYPO_MAP for c in w.lower())]

    if not candidates:
        return text, None

    idx, word = random.choice(candidates)

    # Find a typo-able character
    typo_chars = [(j, c) for j, c in enumerate(word) if c.lower() in _TYPO_MAP]
    if not typo_chars:
        return text, None

    char_idx, char = random.choice(typo_chars)
    replacement = random.choice(_TYPO_MAP[char.lower()])

    # Create typo version
    typo_word = word[:char_idx] + replacement + word[char_idx + 1:]
    words[idx] = typo_word
    typo_text = " ".join(words)

    # Create correction
    correction = random.choice(_CORRECTION_FORMATS).format(correct=word)

    return typo_text, correction
