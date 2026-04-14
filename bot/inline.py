# bot/inline.py
"""
Inline mode — @botname query in any Telegram chat.

When someone types @botname followed by a question in any chat,
the bot responds with an AI-generated answer using its persona.

Uses the first active group's persona as the canonical responder.
Registered in main.py via InlineQueryHandler.
"""

import logging
import uuid

from telegram import InlineQueryResultArticle, InputTextMessageContent, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def handle_inline_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle @botname queries from any chat.

    Empty queries show a usage hint.
    Non-empty queries get an AI response using the first active persona.
    """
    inline_query = update.inline_query
    if inline_query is None:
        return

    text = (inline_query.query or "").strip()

    if not text:
        hint = InlineQueryResultArticle(
            id="hint",
            title="Sual ver...",
            description="Məsələn: '@bot salam' — bot cavab verəcək",
            input_message_content=InputTextMessageContent("..."),
        )
        await inline_query.answer([hint], cache_time=1)
        return

    from bot.database import AsyncSessionLocal
    from bot.ai import generate_reply
    from bot.models import Group
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    # Use first active group's persona
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .where(Group.is_active == True)  # noqa: E712
            .limit(1)
        )
        group = result.scalar_one_or_none()

    if group is None or group.persona is None:
        logger.debug("Inline query: no active group found")
        return

    persona = group.persona

    reply = await generate_reply(
        persona,
        context_messages=[{"role": "user", "content": text}],
        max_tokens=200,
    )

    if not reply:
        return

    result_article = InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title=f"{persona.name} deyir:",
        description=reply[:100] + ("..." if len(reply) > 100 else ""),
        input_message_content=InputTextMessageContent(reply),
    )

    await inline_query.answer([result_article], cache_time=10)
    logger.info("Inline query answered (%d chars): %s", len(reply), text[:60])
