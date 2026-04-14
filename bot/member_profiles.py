# bot/member_profiles.py
"""
Per-member profile tracking.

Tracks each member's activity patterns, message count, last seen,
and AI-generated observations about their personality/interests.

Used to:
  • Let the bot notice when a regular member has been silent
  • Remember individual member facts (birthday, nickname, topics)
  • Generate richer character analysis in the dashboard
"""

import logging
import os
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import MemberProfile, Message

logger = logging.getLogger(__name__)

# How many messages before refreshing the AI-generated profile notes
PROFILE_REFRESH_INTERVAL = int(os.getenv("PROFILE_REFRESH_INTERVAL", "50"))

_PROFILE_SYSTEM = (
    "Sən bir Telegram qrupu üzvünün xarakter analizini aparırsan. "
    "Sənə bu şəxsin yazdığı mesajlar veriləcək. "
    "3-4 cümlə ilə bu şəxs haqqında canlı portret yaz:\n"
    "- Danışıq tərzi və üslubu\n"
    "- Sevdiyi mövzular\n"
    "- Qrupdakı rolu (zarafatçı, ciddi, dinləyici...)\n"
    "- Xarakterik ifadələri varsa qeyd et\n"
    "Azərbaycanca, qısa, canlı yaz."
)


async def get_or_create_profile(
    session: AsyncSession,
    group_id: int,
    sender_id: int,
    sender_name: str,
    sender_username: str | None,
) -> MemberProfile:
    """Get existing profile or create a new one."""
    result = await session.execute(
        select(MemberProfile).where(
            MemberProfile.group_id == group_id,
            MemberProfile.sender_id == sender_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = MemberProfile(
            group_id=group_id,
            sender_id=sender_id,
            sender_name=sender_name,
            sender_username=sender_username,
            message_count=0,
        )
        session.add(profile)
        await session.flush()
    return profile


async def update_member_activity(
    group_id: int,
    sender_id: int,
    sender_name: str,
    sender_username: str | None,
    message_text: str,
    sent_at: datetime,
) -> None:
    """
    Update member profile after each message.

    Opens its own session — safe to call as asyncio.create_task().
    Refreshes AI profile notes every PROFILE_REFRESH_INTERVAL messages.
    """
    from bot.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        profile = await get_or_create_profile(
            session, group_id, sender_id, sender_name, sender_username
        )

        profile.sender_name = sender_name  # keep name up to date
        profile.sender_username = sender_username
        profile.message_count = (profile.message_count or 0) + 1
        profile.last_seen = sent_at

        # Track active hours
        hour = sent_at.hour
        existing_hours = list(map(int, profile.active_hours.split(","))) if profile.active_hours else []
        existing_hours.append(hour)
        # Keep last 200 hours for rolling window
        existing_hours = existing_hours[-200:]
        profile.active_hours = ",".join(map(str, existing_hours))

        # Refresh AI profile notes every N messages
        if profile.message_count % PROFILE_REFRESH_INTERVAL == 0:
            notes = await _generate_profile_notes(session, group_id, sender_id, sender_name)
            if notes:
                profile.profile_notes = notes
                logger.info("Updated profile notes for %s (group %d)", sender_name, group_id)

        await session.commit()


async def _generate_profile_notes(
    session: AsyncSession,
    group_id: int,
    sender_id: int,
    sender_name: str,
) -> str | None:
    """Generate AI profile notes from last 60 messages by this member."""
    result = await session.execute(
        select(Message.text)
        .where(
            Message.group_id == group_id,
            Message.sender_id == sender_id,
            Message.is_bot == False,  # noqa: E712
        )
        .order_by(Message.sent_at.desc())
        .limit(60)
    )
    texts = list(reversed(result.scalars().all()))
    if len(texts) < 10:
        return None

    sample = "\n".join(f"- {t}" for t in texts)
    user_content = f"{sender_name} adlı şəxsin mesajları:\n{sample}\n\nPortret:"

    return await _call_ai(user_content)


async def _call_ai(user_content: str) -> str | None:
    provider = os.getenv("AI_PROVIDER", "openai").lower()
    model_map = {
        "anthropic": os.getenv("MEMORY_MODEL", "claude-haiku-4-5-20251001"),
        "grok": os.getenv("MEMORY_MODEL", "grok-3-mini"),
    }
    model = model_map.get(provider, os.getenv("MEMORY_MODEL", "gpt-4o-mini"))

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic()
            resp = await client.messages.create(
                model=model, max_tokens=200,
                system=_PROFILE_SYSTEM,
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
                model=model, max_tokens=200,
                messages=[
                    {"role": "system", "content": _PROFILE_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
            )
            return resp.choices[0].message.content
    except Exception as e:
        logger.warning("Profile note generation failed: %s", e)
        return None


def get_peak_hours(profile: MemberProfile) -> list[int]:
    """Return top 3 most active hours from the profile."""
    if not profile.active_hours:
        return []
    hours = list(map(int, profile.active_hours.split(",")))
    return [h for h, _ in Counter(hours).most_common(3)]


async def get_silent_members(
    session: AsyncSession,
    group_id: int,
    hours_threshold: int = 48,
) -> list[MemberProfile]:
    """
    Return members who were active recently but silent for hours_threshold hours.
    Used to let the bot notice and ask about them.
    """
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    cutoff_recent = now - timedelta(days=14)   # must have been active in last 2 weeks
    cutoff_silent = now - timedelta(hours=hours_threshold)

    result = await session.execute(
        select(MemberProfile).where(
            MemberProfile.group_id == group_id,
            MemberProfile.last_seen >= cutoff_recent,
            MemberProfile.last_seen <= cutoff_silent,
            MemberProfile.message_count >= 20,  # only regulars
        )
    )
    return list(result.scalars().all())


async def get_todays_birthdays(
    session: AsyncSession,
    group_id: int,
) -> list[MemberProfile]:
    """Return members whose birthday is today (MM-DD format)."""
    from datetime import date
    today = date.today().strftime("%m-%d")
    result = await session.execute(
        select(MemberProfile).where(
            MemberProfile.group_id == group_id,
            MemberProfile.birthday == today,
        )
    )
    return list(result.scalars().all())
