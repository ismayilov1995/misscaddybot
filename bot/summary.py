# bot/summary.py
"""
Hierarchical rolling conversation summaries.

Two levels:
  L1 — summary of raw messages since the last L1 (short-term, every bot tag)
  L2 — meta-summary of every 4 L1 summaries (medium-term memory)

Context injected into each bot reply:
  [L2 if exists] + [last 2 L1s after that L2] + [raw messages since last L1]

This gives the bot three temporal layers:
  • What kind of group this is and what happened over many sessions (L2)
  • What happened in the last few conversation batches (recent L1s)
  • What is happening right now (raw messages)
"""

import logging
import os

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import GroupSummary, Message

logger = logging.getLogger(__name__)

MIN_MESSAGES_FOR_SUMMARY = int(os.getenv("MIN_MESSAGES_FOR_SUMMARY", "3"))
L2_TRIGGER_COUNT = int(os.getenv("L2_TRIGGER_COUNT", "4"))   # L1s needed to generate an L2
L1_IN_CONTEXT = int(os.getenv("L1_IN_CONTEXT", "2"))         # how many recent L1s to show the bot

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_L1_SYSTEM = (
    "Sən bir Telegram qrupunun yaddaş sistemisin. "
    "Sənə yeni mesajlar veriləcək. Bu mesajları əsas götürərək iki hissəli xülasə yaz:\n\n"
    "## QRUP PORTRETİ\n"
    "Əvvəlki portret varsa onu əsas götür, yeni məlumatla yenilə. Yaz:\n"
    "- Hər üzvün xarakteri, danışıq tərzi, sevdiyi mövzular\n"
    "- Kim kiminlə zarafatlaşır, kimlər yaxındır, kimlər tez dalaşır\n"
    "- Qrupdakı inside joke-lar, ləqəblər, təkrarlanan sözlər\n\n"
    "## SON SÖHBƏT\n"
    "YALNIZ bu batçdakı yeni mesajları əks etdir — əvvəlki batçları buraya yazma. Yaz:\n"
    "- Nə müzakirə edildi, hansı mövzular çıxdı\n"
    "- Maraqlı anlar, zarafatlar, mübahisələr\n"
    "- İndiki əhval-ruhiyyə: qrup indi nə hissdədir\n\n"
    "Hər hissə maksimum 120 söz. Azərbaycanca. Quru siyahı yox, canlı yaz."
)

_L2_SYSTEM = (
    "Sən bir Telegram qrupunun uzunmüddətli yaddaşını formalaşdırırsan. "
    "Sənə bir neçə ardıcıl L1 xülasəsi veriləcək — hər biri ayrı söhbət dövrünü əhatə edir. "
    "Bunlardan QRUPun dərin portretini çıxar:\n\n"
    "- Üzvlərin əsl xarakteri: zamanla nə görürsən, ilk baxışdan fərqli nə var?\n"
    "- Münasibətlərin dinamikası: kim kiminlə hansı vəziyyətdə nə edir?\n"
    "- Qrupun dəyişməz temaları: həmişə nəyə qayıdırlar?\n"
    "- Inside joke-lar, ləqəblər, ritual sözlər — bunlar nə vaxt çıxır?\n"
    "- Qrupun ümumi ruhu: bu insanları bir arada tutan nədir?\n\n"
    "Maksimum 250 söz. Azərbaycanca. Bu uzunmüddətli yaddaş olacaq — "
    "dəqiq, zəngin, canlı yaz."
)


# ---------------------------------------------------------------------------
# DB reads
# ---------------------------------------------------------------------------

async def get_latest_summary(
    session: AsyncSession,
    group_id: int,
) -> tuple[str | None, int | None]:
    """Return (summary_text, last_message_id) for the most recent L1 summary."""
    result = await session.execute(
        select(GroupSummary)
        .where(GroupSummary.group_id == group_id, GroupSummary.level == 1)
        .order_by(GroupSummary.id.desc())
        .limit(1)
    )
    summary = result.scalar_one_or_none()
    if summary is None:
        return None, None
    return summary.summary, summary.last_message_id


async def get_summary_context(
    session: AsyncSession,
    group_id: int,
) -> str:
    """
    Build the full summary context string to inject into the system prompt.

    Structure:
      [L2 uzunmüddətli yaddaş]  ← medium-term, generated every 4 L1s
      [Son L1 xülasələri]        ← last L1_IN_CONTEXT summaries after the L2
    """
    parts: list[str] = []

    # --- Latest L2 ---
    l2_result = await session.execute(
        select(GroupSummary)
        .where(GroupSummary.group_id == group_id, GroupSummary.level == 2)
        .order_by(GroupSummary.id.desc())
        .limit(1)
    )
    latest_l2 = l2_result.scalar_one_or_none()

    if latest_l2:
        parts.append(f"## Uzunmüddətli yaddaş\n{latest_l2.summary}")

    # --- Recent L1s (after L2 if exists) ---
    l1_query = (
        select(GroupSummary)
        .where(GroupSummary.group_id == group_id, GroupSummary.level == 1)
        .order_by(GroupSummary.id.desc())
        .limit(L1_IN_CONTEXT)
    )
    if latest_l2:
        l1_query = l1_query.where(GroupSummary.id > latest_l2.id)

    l1_result = await session.execute(l1_query)
    recent_l1s = list(reversed(l1_result.scalars().all()))

    if recent_l1s:
        l1_text = "\n\n---\n\n".join(s.summary for s in recent_l1s)
        parts.append(f"## Son söhbət xülasəsi\n{l1_text}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Summary generation (public entry point)
# ---------------------------------------------------------------------------

async def maybe_generate_summary(
    group_id: int,
    telegram_id: int,
) -> None:
    """
    Generate an L1 summary of messages since the last L1.
    Then check if 4 new L1s exist since the last L2 — if so, generate L2.

    Opens its own DB session — safe to call as asyncio.create_task().
    """
    from bot.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        # --- L1: summarize new messages ---
        _, last_l1_msg_id = await get_latest_summary(session, group_id)

        new_msg_count = await _count_messages(session, group_id, after_id=last_l1_msg_id)
        if new_msg_count < MIN_MESSAGES_FOR_SUMMARY:
            logger.debug(
                "Skipping L1 summary for group %d: only %d new messages",
                telegram_id, new_msg_count,
            )
            return

        logger.info(
            "Generating L1 summary for group %d (%d new messages)",
            telegram_id, new_msg_count,
        )

        messages = await _fetch_messages(session, group_id, after_id=last_l1_msg_id)
        if not messages:
            return

        prev_l1_text, _ = await get_latest_summary(session, group_id)
        l1_text = await _generate_l1(messages, prev_l1_text)
        if not l1_text:
            return

        new_l1 = GroupSummary(
            group_id=group_id,
            summary=l1_text,
            last_message_id=messages[-1].id,
            level=1,
        )
        session.add(new_l1)
        await session.flush()   # get new_l1.id without closing session

        logger.info(
            "L1 summary stored for group %d (up to message id %d)",
            telegram_id, messages[-1].id,
        )

        # --- L2: check if we should generate a meta-summary ---
        await _maybe_generate_l2(session, group_id, telegram_id)

        await session.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _count_messages(
    session: AsyncSession,
    group_id: int,
    after_id: int | None,
) -> int:
    query = select(func.count()).where(Message.group_id == group_id)
    if after_id is not None:
        query = query.where(Message.id > after_id)
    return (await session.execute(query)).scalar() or 0


async def _fetch_messages(
    session: AsyncSession,
    group_id: int,
    after_id: int | None,
) -> list:
    query = (
        select(Message)
        .where(Message.group_id == group_id)
        .order_by(Message.sent_at.asc())
    )
    if after_id is not None:
        query = query.where(Message.id > after_id)
    result = await session.execute(query)
    return list(result.scalars().all())


async def _maybe_generate_l2(
    session: AsyncSession,
    group_id: int,
    telegram_id: int,
) -> None:
    """Generate an L2 meta-summary if L2_TRIGGER_COUNT new L1s exist since the last L2."""
    # Find latest L2
    l2_result = await session.execute(
        select(GroupSummary)
        .where(GroupSummary.group_id == group_id, GroupSummary.level == 2)
        .order_by(GroupSummary.id.desc())
        .limit(1)
    )
    latest_l2 = l2_result.scalar_one_or_none()

    # Count L1s since that L2
    l1_count_query = (
        select(func.count())
        .where(GroupSummary.group_id == group_id, GroupSummary.level == 1)
    )
    if latest_l2:
        l1_count_query = l1_count_query.where(GroupSummary.id > latest_l2.id)

    l1_count = (await session.execute(l1_count_query)).scalar() or 0

    if l1_count < L2_TRIGGER_COUNT:
        logger.debug(
            "L2 not triggered for group %d: %d/%d L1s",
            telegram_id, l1_count, L2_TRIGGER_COUNT,
        )
        return

    logger.info(
        "Generating L2 meta-summary for group %d (%d L1s)",
        telegram_id, l1_count,
    )

    # Fetch those L1s
    l1_query = (
        select(GroupSummary)
        .where(GroupSummary.group_id == group_id, GroupSummary.level == 1)
        .order_by(GroupSummary.id.asc())
    )
    if latest_l2:
        l1_query = l1_query.where(GroupSummary.id > latest_l2.id)

    l1_result = await session.execute(l1_query)
    l1_summaries = list(l1_result.scalars().all())

    l2_text = await _generate_l2(l1_summaries)
    if not l2_text:
        return

    # L2's last_message_id = the highest one among all those L1s
    max_msg_id = max(s.last_message_id for s in l1_summaries)
    session.add(GroupSummary(
        group_id=group_id,
        summary=l2_text,
        last_message_id=max_msg_id,
        level=2,
    ))
    logger.info("L2 meta-summary stored for group %d", telegram_id)


async def _generate_l1(messages: list, prev_summary: str | None) -> str | None:
    """Summarize a batch of raw messages into an L1 summary."""
    lines = [
        f"{'Bot' if m.is_bot else m.sender_name}: {m.text}"
        for m in messages
    ]
    convo = "\n".join(lines)

    prompt_parts = []
    if prev_summary:
        prompt_parts.append(f"Əvvəlki xülasə (QRUP PORTRETİ hissəsini yenilə):\n{prev_summary}")
    prompt_parts.append(f"Yeni mesajlar:\n{convo}\n\nYenilənmiş xülasə:")

    return await _call_ai("\n\n".join(prompt_parts), system=_L1_SYSTEM)


async def _generate_l2(l1_summaries: list) -> str | None:
    """Combine multiple L1 summaries into a deep L2 meta-summary."""
    parts = []
    for i, s in enumerate(l1_summaries, 1):
        parts.append(f"=== Dövrə {i} ===\n{s.summary}")
    user_content = "\n\n".join(parts) + "\n\nDərin portret:"

    return await _call_ai(user_content, system=_L2_SYSTEM)


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


async def _call_ai(user_content: str, system: str) -> str | None:
    provider = os.getenv("AI_PROVIDER", "openai").lower()
    model = _get_summary_model()

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic()
            resp = await client.messages.create(
                model=model,
                max_tokens=400,
                system=system,
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
                max_tokens=400,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            return resp.choices[0].message.content
        else:
            import openai
            client = openai.AsyncOpenAI()
            resp = await client.chat.completions.create(
                model=model,
                max_tokens=400,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            return resp.choices[0].message.content
    except Exception as e:
        logger.warning("Summary generation failed: %s", e)
        return None
