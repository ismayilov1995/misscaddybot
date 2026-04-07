# bot/handlers.py
import logging
from datetime import datetime

import telegram
from telegram import Update
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import Group, Message, Persona

logger = logging.getLogger(__name__)


async def get_group_with_persona(
    session: AsyncSession, telegram_id: int
) -> tuple[Group, Persona] | None:
    """
    Query Group by Telegram chat ID, eagerly loading the related Persona.

    Returns (group, persona) if found, None if the group has not been seeded.
    The caller is responsible for handling None — unregistered groups are skipped silently.
    """
    result = await session.execute(
        select(Group)
        .options(selectinload(Group.persona))
        .where(Group.telegram_id == telegram_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        return None
    return (group, group.persona)


async def save_message(
    session: AsyncSession,
    group_id: int,
    telegram_message_id: int,
    sender_id: int,
    sender_name: str,
    sender_username: str | None,
    text: str,
    is_bot: bool,
    replied_to_id: int | None,
    sent_at: datetime,
) -> Message:
    """
    Persist one Message row and return the saved ORM object.

    expire_on_commit=False is set on AsyncSessionLocal — attributes are accessible
    after commit without an extra SELECT.
    """
    message = Message(
        group_id=group_id,
        telegram_message_id=telegram_message_id,
        sender_id=sender_id,
        sender_name=sender_name,
        sender_username=sender_username,
        text=text,
        is_bot=is_bot,
        replied_to_id=replied_to_id,
        sent_at=sent_at,
    )
    session.add(message)
    await session.commit()
    return message


def is_mentioned(
    message: telegram.Message,
    bot_username: str,
    persona_name: str,
    bot_id: int,
) -> bool:
    """
    Return True if the bot is addressed in this message.

    Three detection cases (any one is sufficient):
      1. @username entity matches the bot's username (case-insensitive)
      2. Persona name appears anywhere in the message text (case-insensitive)
      3. Message is a direct reply to a message sent by the bot

    Pure function — no I/O, no DB calls, no side effects.
    """
    # Case 1: @username mention entity
    for entity in message.entities or []:
        if entity.type == MessageEntityType.MENTION:
            entity_text = message.text[entity.offset : entity.offset + entity.length]
            if entity_text.lower() == f"@{bot_username}".lower():
                return True

    # Case 2: persona name in message body
    if persona_name.lower() in (message.text or "").lower():
        return True

    # Case 3: direct reply to a bot message
    if (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
        and message.reply_to_message.from_user.id == bot_id
    ):
        return True

    return False


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    PTB MessageHandler callback — saves every group text message to the DB.

    Registered in main.py for: filters.TEXT & filters.ChatType.GROUPS

    Skips silently if:
    - update.effective_message is None (should not happen with this filter, but defensive)
    - message.text is None (photo-only, sticker, or service messages)
    - group is not in the DB (not yet seeded via seed.py)
    """
    # Import here — load_dotenv() and env validation have already run in main.py
    from bot.database import AsyncSessionLocal

    message = update.effective_message
    if message is None or message.text is None:
        return

    chat_id = message.chat_id

    async with AsyncSessionLocal() as session:
        result = await get_group_with_persona(session, chat_id)
        if result is None:
            return  # Group not seeded — skip silently
        group, persona = result

        sender_id = message.from_user.id
        sender_name = " ".join(
            filter(None, [message.from_user.first_name, message.from_user.last_name])
        )
        sender_username = message.from_user.username
        replied_to_id = (
            message.reply_to_message.message_id if message.reply_to_message else None
        )
        sent_at = message.date

        await save_message(
            session,
            group.id,
            message.message_id,
            sender_id,
            sender_name,
            sender_username,
            message.text,
            False,
            replied_to_id,
            sent_at,
        )

    if is_mentioned(message, context.bot.username, persona.name, context.bot.id):
        logger.info(
            "Mention detected in group %d — queuing reply (Phase 4)", chat_id
        )
