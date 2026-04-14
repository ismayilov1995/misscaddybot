# bot/weekly_digest.py
"""
Weekly group digest — sent every Sunday.

Generates a fun "qrup xəbərləri" summary of the week:
  • Most active member
  • Most discussed topics
  • Best quote of the week
  • Mood summary
  • A light-hearted closing from the persona

Feels like a real group member doing a weekly recap.
"""

import logging
import os
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Group, Message, MemberProfile, Persona

logger = logging.getLogger(__name__)

_DIGEST_SYSTEM = (
    "Sən bir Telegram qrupunun həftəlik xülasəsini yazırsan. "
    "Sənə həftənin mesajları veriləcək. "
    "Əyləncəli, qısa, qrupun öz tərzi ilə bir 'həftəlik xəbər' yaz. "
    "Format:\n"
    "🏆 Həftənin ən aktivi: [ad]\n"
    "🔥 Ən çox danışılan mövzu: [mövzu]\n"
    "💬 Həftənin sözü: [qrupdan bir maraqlı cümlə]\n"
    "📊 Əhval-ruhiyyə: [bir söz: enerjili/sakit/zarafatçıl/ciddi/qarışıq]\n"
    "✍️ Xülasə: [2-3 cümlə, əyləncəli, qrupun dilinə uyğun]\n\n"
    "Azərbaycanca yaz. Rəsmi dil yox, qrup yazışması tərzi."
)


async def generate_weekly_digest(
    group_id: int,
    telegram_id: int,
    persona: Persona,
) -> str | None:
    """
    Generate and return the weekly digest text.
    Called by the scheduler every Sunday.
    """
    from bot.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        # Fetch messages from the past week
        result = await session.execute(
            select(Message)
            .where(
                Message.group_id == group_id,
                Message.sent_at >= week_ago,
                Message.is_bot == False,  # noqa: E712
            )
            .order_by(Message.sent_at.asc())
        )
        messages = result.scalars().all()

        if len(messages) < 15:
            logger.info(
                "Digest skipped for group %d — only %d messages this week",
                telegram_id, len(messages),
            )
            return None

        # Most active member
        name_counts: dict[str, int] = {}
        for m in messages:
            name_counts[m.sender_name] = name_counts.get(m.sender_name, 0) + 1
        most_active = max(name_counts, key=name_counts.__getitem__)

        # Sample of messages for AI
        sample_msgs = messages[::max(1, len(messages) // 40)][:40]
        convo = "\n".join(f"{m.sender_name}: {m.text}" for m in sample_msgs)

        stats = (
            f"Həftə ərzində {len(messages)} mesaj yazıldı. "
            f"Ən aktiv: {most_active} ({name_counts[most_active]} mesaj). "
            f"İştirakçı sayı: {len(name_counts)} nəfər."
        )

        user_content = f"Statistika: {stats}\n\nMesajlardan nümunə:\n{convo}\n\nHəftəlik xəbər:"

        digest = await _call_ai(user_content)

        if digest:
            # Add persona's personal sign-off
            sign_offs = [
                f"\n\n— {persona.name} 😄",
                f"\n\n{persona.name} xəbər verdi 📰",
                f"\n\nHəftəyə xoş gəldiniz! — {persona.name}",
            ]
            digest += random.choice(sign_offs)

        return digest


async def _call_ai(user_content: str) -> str | None:
    provider = os.getenv("AI_PROVIDER", "openai").lower()
    model_map = {
        "anthropic": os.getenv("SUMMARY_MODEL", "claude-haiku-4-5-20251001"),
        "grok": os.getenv("SUMMARY_MODEL", "grok-3-mini"),
    }
    model = model_map.get(provider, os.getenv("SUMMARY_MODEL", "gpt-4o-mini"))

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic()
            resp = await client.messages.create(
                model=model, max_tokens=400,
                system=_DIGEST_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            )
            return resp.content[0].text
        elif provider == "grok":
            import openai
            client = openai.AsyncOpenAI(
                api_key=os.getenv("XAI_API_KEY"), base_url="https://api.x.ai/v1"
            )
        else:
            import openai
            client = openai.AsyncOpenAI()

        if provider != "anthropic":
            resp = await client.chat.completions.create(
                model=model, max_tokens=400,
                messages=[
                    {"role": "system", "content": _DIGEST_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
            )
            return resp.choices[0].message.content
    except Exception as e:
        logger.warning("Weekly digest generation failed: %s", e)
        return None
