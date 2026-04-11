# bot/handlers.py
import asyncio
import logging
import random
from datetime import datetime

import telegram
from telegram import Update
from telegram.constants import ChatAction, MessageEntityType
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


async def get_context_messages(
    session: AsyncSession,
    group_id: int,
    limit: int,
    after_message_id: int | None = None,
) -> list[dict]:
    """
    Fetch recent messages for a group and return them as Claude message dicts.

    If after_message_id is provided, only returns messages after that ID
    (used with rolling summaries — the summary covers everything before).

    Returns messages in chronological order (oldest first).
    is_bot=True  → {"role": "assistant", "content": text}
    is_bot=False → {"role": "user", "content": "{sender_name}: {text}"}
    """
    query = select(Message).where(Message.group_id == group_id)
    if after_message_id is not None:
        query = query.where(Message.id > after_message_id)
    result = await session.execute(
        query.order_by(Message.sent_at.desc()).limit(limit)
    )
    rows = list(reversed(result.scalars().all()))
    messages = []
    for row in rows:
        role = "assistant" if row.is_bot else "user"
        content = row.text if row.is_bot else f"{row.sender_name}: {row.text}"
        # Merge consecutive same-role messages (required by Anthropic)
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += f"\n{content}"
        else:
            messages.append({"role": role, "content": content})
    return messages


async def reply_to_mention(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group: Group,
    persona: Persona,
) -> None:
    """
    Full reactive reply loop — called as a background task when a mention is detected.

    Steps:
      1. Fetch recent context messages from DB
      2. Call Claude API via generate_reply
      3. If None (API error) → return silently, no message sent
      4. Send typing indicator
      5. Sleep for realistic human-like delay (base 1–4s + length-scaled)
      6. Send reply to chat
      7. Save bot's outgoing message to DB
    """
    from bot.database import AsyncSessionLocal
    from bot.ai import generate_reply

    chat_id = update.effective_message.chat_id

    async with AsyncSessionLocal() as session:
        from bot.summary import get_latest_summary, maybe_generate_summary
        summary_text, last_msg_id = await get_latest_summary(session, group.id)

        context_messages = await get_context_messages(
            session, group.id, persona.context_window,
            after_message_id=last_msg_id,
        )

        # Ensure minimum context — if too few messages after summary, fetch more
        min_context = 8
        if len(context_messages) < min_context:
            context_messages = await get_context_messages(
                session, group.id, min_context,
            )

        from bot.memory import get_memory_context, maybe_update_memory
        memory_context = await get_memory_context(session, group.id, context_messages)

        reply = await generate_reply(
            persona, context_messages,
            memory_context=memory_context,
            summary_context=summary_text or "",
        )
        if reply is None:
            return

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        delay = random.uniform(1, 4) + min(len(reply) * 0.04, 8)
        await asyncio.sleep(delay)

        sent_msg = await context.bot.send_message(chat_id=chat_id, text=reply)

        await save_message(
            session,
            group_id=group.id,
            telegram_message_id=sent_msg.message_id,
            sender_id=context.bot.id,
            sender_name=persona.name,
            sender_username=context.bot.username,
            text=reply,
            is_bot=True,
            replied_to_id=None,
            sent_at=sent_msg.date,
        )

    asyncio.create_task(maybe_update_memory(group, context_messages))
    asyncio.create_task(maybe_generate_summary(group.id, group.telegram_id))


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
        logger.info("Mention detected in group %d — spawning reply task", chat_id)
        asyncio.create_task(reply_to_mention(update, context, group, persona))


async def handle_bot_added(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    ChatMemberHandler callback — fires when the bot's own membership status changes.

    Registered in main.py for: ChatMemberUpdated where new_chat_member is the bot
    and new status is 'member' or 'administrator'.

    Auto-seeds Group + Persona so manual seed.py is not required after deploy.
    Re-adding to an existing group is a no-op (group already in DB).
    """
    from bot.database import AsyncSessionLocal
    from seed import (
        DEFAULT_NAME, DEFAULT_BIO, DEFAULT_PERSONALITY,
        DEFAULT_LANGUAGE_STYLE, DEFAULT_AUTO_MESSAGE_ENABLED,
        DEFAULT_AUTO_MESSAGE_INTERVAL_MIN, DEFAULT_AUTO_MESSAGE_INTERVAL_MAX,
        DEFAULT_CONTEXT_WINDOW,
    )

    my_chat_member = update.my_chat_member
    if my_chat_member is None:
        return

    new_status = my_chat_member.new_chat_member.status
    if new_status not in ("member", "administrator"):
        return

    chat = my_chat_member.chat
    if chat.type not in ("group", "supergroup"):
        return

    chat_id = chat.id
    title = chat.title or "Unknown Group"

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group).where(Group.telegram_id == chat_id)
        )
        if result.scalar_one_or_none() is not None:
            logger.info("Bot re-added to known group %d — skipping seed", chat_id)
            return

        group = Group(telegram_id=chat_id, title=title, is_active=True)
        session.add(group)
        await session.flush()

        persona = Persona(
            group_id=group.id,
            name=DEFAULT_NAME,
            bio=DEFAULT_BIO,
            personality=DEFAULT_PERSONALITY,
            language_style=DEFAULT_LANGUAGE_STYLE,
            auto_message_enabled=DEFAULT_AUTO_MESSAGE_ENABLED,
            auto_message_interval_min=DEFAULT_AUTO_MESSAGE_INTERVAL_MIN,
            auto_message_interval_max=DEFAULT_AUTO_MESSAGE_INTERVAL_MAX,
            context_window=DEFAULT_CONTEXT_WINDOW,
        )
        session.add(persona)
        await session.commit()

    logger.info("Auto-seeded group '%s' (%d) with persona '%s'", title, chat_id, DEFAULT_NAME)
