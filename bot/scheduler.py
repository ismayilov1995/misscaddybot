# bot/scheduler.py
import asyncio
import logging
import random

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.models import Group, Persona

logger = logging.getLogger(__name__)


async def send_auto_message(application) -> None:
    """
    APScheduler job — sends a spontaneous message to every active group
    where auto_message_enabled=True.

    Fetches recent context, calls Claude, sends reply, saves to DB.
    Errors are caught per-group so one failure does not block others.
    """
    from bot.database import AsyncSessionLocal
    from bot.ai import generate_reply
    from bot.handlers import get_context_messages, save_message

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .where(Group.is_active == True)  # noqa: E712
        )
        groups = result.scalars().all()

    for group in groups:
        persona = group.persona
        if persona is None or not persona.auto_message_enabled:
            continue

        try:
            async with AsyncSessionLocal() as session:
                from bot.summary import get_summary_context, maybe_generate_summary

                summary_context = await get_summary_context(session, group.id)

                context_messages = await get_context_messages(
                    session, group.id, persona.context_window,
                )

            # 20% chance: conversation starter — longer, topic-opening message
            is_conversation_starter = random.random() < 0.20
            if is_conversation_starter:
                starter_hint = (
                    "İndi söhbətə yeni mövzu aç. Maraqlı bir şey paylaş, sual soruş, "
                    "fikir bildir — qrupdakıların cavab vermək istəyəcəyi bir şey olsun. "
                    "Qrupun maraqlarına və əvvəlki söhbətlərə uyğun mövzu seç. "
                    "Təbii yaz, sanki ağlına gəldi."
                )
                reply = await generate_reply(
                    persona, context_messages,
                    memory_context=starter_hint,
                    summary_context=summary_context,
                    max_tokens=500,
                )
                logger.info("Conversation starter sent to group %d", group.telegram_id)
            else:
                reply = await generate_reply(persona, context_messages, summary_context=summary_context)

            if reply is None:
                logger.warning("Auto-message skipped for group %d — Claude returned None", group.telegram_id)
                continue

            sent_msg = await application.bot.send_message(
                chat_id=group.telegram_id, text=reply
            )

            async with AsyncSessionLocal() as session:
                await save_message(
                    session,
                    group_id=group.id,
                    telegram_message_id=sent_msg.message_id,
                    sender_id=application.bot.id,
                    sender_name=persona.name,
                    sender_username=application.bot.username,
                    text=reply,
                    is_bot=True,
                    replied_to_id=None,
                    sent_at=sent_msg.date,
                )

            logger.info("Auto-message sent to group %d", group.telegram_id)
            asyncio.create_task(maybe_generate_summary(group.id, group.telegram_id))

        except Exception as e:
            logger.warning("Auto-message failed for group %d: %s", group.telegram_id, e)


async def update_group_memory(application) -> None:
    """
    APScheduler job — runs every 24 hours.

    For each active group, fetches the last 100 messages, sends them to Claude
    and asks it to write short observations about the group (inside jokes,
    recurring topics, who's who, group vibe). Saves the result to persona.memory.

    This memory is then injected into the system prompt on every reply,
    allowing the bot's character to evolve and adapt to the group over time.
    """
    from bot.database import AsyncSessionLocal
    from bot.handlers import get_context_messages

    async with AsyncSessionLocal() as session:
        from sqlalchemy.orm import selectinload
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .where(Group.is_active == True)  # noqa: E712
        )
        groups = result.scalars().all()

    for group in groups:
        persona = group.persona
        if persona is None:
            continue

        try:
            async with AsyncSessionLocal() as session:
                messages = await get_context_messages(session, group.id, limit=100)

            if len(messages) < 10:
                logger.info("Group %d has < 10 messages — skipping memory update", group.telegram_id)
                continue

            # Format messages as plain text for the reflection prompt
            convo = "\n".join(
                f"{'Bot' if m['role'] == 'assistant' else 'İnsan'}: {m['content']}"
                for m in messages
            )

            reflection_prompt = (
                "Aşağıda bir Telegram qrupunun söhbət tarixçəsi var. "
                "Sən bu qrupun üzvüsən və bu söhbəti oxuyursan.\n\n"
                f"{convo}\n\n"
                "Bu söhbətə əsaslanaraq qrup haqqında 3-5 cümlə ilə qeyd yaz: "
                "kim kimdir, nə mövzular çıxır, hansı inside joke-lar var, qrupun ümumi havası necədir. "
                "Şəxsi qeyd kimi yaz, sanki öz notlarındır."
            )

            import anthropic
            import os
            client = anthropic.AsyncAnthropic()
            response = await client.messages.create(
                model=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
                max_tokens=300,
                messages=[{"role": "user", "content": reflection_prompt}],
            )
            new_memory = response.content[0].text.strip()

            async with AsyncSessionLocal() as session:
                from sqlalchemy import select as sa_select
                result = await session.execute(
                    sa_select(Persona).where(Persona.group_id == group.id)
                )
                p = result.scalar_one_or_none()
                if p:
                    p.memory = new_memory
                    await session.commit()

            logger.info("Memory updated for group %d", group.telegram_id)

        except Exception as e:
            logger.warning("Memory update failed for group %d: %s", group.telegram_id, e)


def build_scheduler(application) -> AsyncIOScheduler:
    """
    Create and configure the AsyncIOScheduler.

    Interval is randomized per-run: each job execution schedules the next
    trigger at a random point within [interval_min, interval_max] minutes.
    We achieve this by using a fixed short-interval trigger (1 min) and
    tracking state via a simple approach: use interval trigger with jitter.

    Simpler approach: use interval trigger with the minimum interval and
    add jitter equal to (max - min) minutes.
    """
    scheduler = AsyncIOScheduler()

    # Default interval: 45 min base + up to 135 min jitter = 45–180 min range
    # These are the defaults; per-group intervals are read at job execution time
    # from the Persona record so they are always up-to-date.
    scheduler.add_job(
        send_auto_message,
        trigger="interval",
        minutes=45,
        jitter=135 * 60,  # jitter in seconds: up to 135 extra minutes
        args=[application],
        id="auto_message",
        name="Auto message job",
        replace_existing=True,
    )

    scheduler.add_job(
        update_group_memory,
        trigger="interval",
        hours=24,
        args=[application],
        id="update_memory",
        name="Group memory update",
        replace_existing=True,
    )

    return scheduler
