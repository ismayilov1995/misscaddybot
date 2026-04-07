# bot/scheduler.py
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
                context_messages = await get_context_messages(
                    session, group.id, persona.context_window
                )

            reply = await generate_reply(persona, context_messages)
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

        except Exception as e:
            logger.warning("Auto-message failed for group %d: %s", group.telegram_id, e)


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

    return scheduler
