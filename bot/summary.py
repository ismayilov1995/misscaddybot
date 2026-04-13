# bot/summary.py
"""
Rolling conversation summaries for cost-efficient context.

Instead of sending the last N raw messages to the AI on every reply,
we periodically summarize batches of messages and store them.
Context becomes: latest summary + messages since that summary.

Summary generation uses a cheaper model (default: Haiku) to minimize cost.
The summary is injected into the system prompt where it gets cached by
Anthropic's prompt caching, so repeated requests only pay for new messages.
"""

import logging
import os

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import GroupSummary, Message

logger = logging.getLogger(__name__)

# Minimum new messages before generating a summary (avoids summarizing 1-2 messages)
MIN_MESSAGES_FOR_SUMMARY = int(os.getenv("MIN_MESSAGES_FOR_SUMMARY", "3"))

_SUMMARY_SYSTEM = (
    "Sən bir Telegram qrupunun yaddaş sistemisin. "
    "Sənə əvvəlki xülasə (varsa) və yeni mesajlar veriləcək. "
    "DƏQİQ BU FORMATDA iki hissəli xülasə yaz:\n\n"
    "## QRUP PORTRETİ\n"
    "Əvvəlki portret varsa onu əsas götür, yeni məlumatla yenilə. Yaz:\n"
    "- Hər üzvün xarakteri, danışıq tərzi, sevdiyi mövzular\n"
    "- Kim kiminlə zarafatlaşır, kimlər yaxındır, kimlər tez dalaşır\n"
    "- Qrupdakı inside joke-lar, ləqəblər, təkrarlanan sözlər\n\n"
    "## SON SÖHBƏT\n"
    "YALNIZ bu batçdakı yeni mesajları əks etdir — köhnəni buraya yazma. Yaz:\n"
    "- Nə müzakirə edildi, hansı mövzular çıxdı\n"
    "- Maraqlı anlar, zarafatlar, mübahisələr\n"
    "- İndiki əhval-ruhiyyə: qrup indi nə hissdədir\n\n"
    "Hər hissə maksimum 150 söz. Azərbaycanca. Quru siyahı yox, canlı yaz."
)


def _get_summary_model() -> str:
    explicit = os.getenv("SUMMARY_MODEL")
    if explicit:
        return explicit
    provider = os.getenv("AI_PROVIDER", "openai").lower()
    if provider == "anthropic":
        return "claude-haiku-4-5-20251001"
    if provider == "grok":
        return "grok-3-mini"
    return "gpt-4o-mini"


# ---------------------------------------------------------------------------
# DB reads
# ---------------------------------------------------------------------------

async def get_latest_summary(
    session: AsyncSession,
    group_id: int,
) -> tuple[str | None, int | None]:
    """
    Return (summary_text, last_message_id) for the most recent summary.
    Returns (None, None) if no summary exists yet.
    """
    result = await session.execute(
        select(GroupSummary)
        .where(GroupSummary.group_id == group_id)
        .order_by(GroupSummary.id.desc())
        .limit(1)
    )
    summary = result.scalar_one_or_none()
    if summary is None:
        return None, None
    return summary.summary, summary.last_message_id


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------

async def maybe_generate_summary(
    group_id: int,
    telegram_id: int,
) -> None:
    """
    Generate a rolling summary of all messages since the last summary.

    Called when the bot is tagged or sends an auto-message — not on every
    incoming message, so there is no per-message DB overhead.

    Opens its own DB session — safe to call as asyncio.create_task().
    """
    from bot.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        _, last_msg_id = await get_latest_summary(session, group_id)

        # Count messages since last summary
        query = select(func.count()).where(Message.group_id == group_id)
        if last_msg_id is not None:
            query = query.where(Message.id > last_msg_id)

        count = (await session.execute(query)).scalar() or 0

        if count < MIN_MESSAGES_FOR_SUMMARY:
            return

        logger.info(
            "Generating summary for group %d (%d messages since last)",
            telegram_id, count,
        )

        # Fetch messages to summarize
        msg_query = (
            select(Message)
            .where(Message.group_id == group_id)
            .order_by(Message.sent_at.asc())
        )
        if last_msg_id is not None:
            msg_query = msg_query.where(Message.id > last_msg_id)

        result = await session.execute(msg_query)
        messages = result.scalars().all()

        if not messages:
            return

        # Build conversation text for the summarizer
        lines = []
        for m in messages:
            sender = "Bot" if m.is_bot else m.sender_name
            lines.append(f"{sender}: {m.text}")
        convo = "\n".join(lines)

        # Get previous summary for continuity
        prev_summary, _ = await get_latest_summary(session, group_id)

        prompt_parts = []
        if prev_summary:
            prompt_parts.append(f"Əvvəlki xülasə:\n{prev_summary}\n")
        prompt_parts.append(f"Yeni mesajlar:\n{convo}\n\nYenilənmiş xülasə:")

        user_content = "\n".join(prompt_parts)
        summary_text = await _generate_summary_text(user_content)
        if not summary_text:
            return

        last_message = messages[-1]
        session.add(GroupSummary(
            group_id=group_id,
            summary=summary_text,
            last_message_id=last_message.id,
        ))
        await session.commit()
        logger.info(
            "Summary stored for group %d (up to message id %d)",
            telegram_id, last_message.id,
        )


async def _generate_summary_text(user_content: str) -> str | None:
    """Generate summary using the configured AI provider with SUMMARY_MODEL."""
    provider = os.getenv("AI_PROVIDER", "openai").lower()
    model = _get_summary_model()

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic()
            resp = await client.messages.create(
                model=model,
                max_tokens=300,
                system=_SUMMARY_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            )
            return resp.content[0].text
        elif provider == "grok":
            import openai
            client = openai.AsyncOpenAI(
                api_key=os.getenv("XAI_API_KEY"),
                base_url="https://api.x.ai/v1",
            )
            resp = await client.chat.completions.create(
                model=model,
                max_tokens=300,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
            )
            return resp.choices[0].message.content
        else:
            import openai
            client = openai.AsyncOpenAI()
            resp = await client.chat.completions.create(
                model=model,
                max_tokens=300,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
            )
            return resp.choices[0].message.content
    except Exception as e:
        logger.warning("Summary generation failed: %s", e)
        return None
