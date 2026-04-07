# tests/test_handlers.py
"""
Tests for bot/handlers.py — DB persistence and mention detection.

DB tests use in-memory SQLite via the handler_session fixture.
PTB object tests use MagicMock to simulate telegram.Message and Update.
No live Telegram API or database connection required.
"""
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.handlers import get_group_with_persona, is_mentioned, save_message, handle_message
from bot.models import Base, Group, Message, Persona
from telegram.constants import MessageEntityType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def handler_session():
    """
    Creates an isolated in-memory SQLite engine, creates all tables, patches
    bot.database.AsyncSessionLocal to use it, and yields the sessionmaker for
    assertion queries.

    DATABASE_URL is set in the environment before importing bot.database so the
    module-level read of os.environ["DATABASE_URL"] in database.py does not fail.
    """
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite+aiosqlite:///:memory:"}):
        import bot.database  # ensure module imported with DATABASE_URL set  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    with patch("bot.database.AsyncSessionLocal", factory):
        yield factory

    await engine.dispose()


@pytest.fixture
async def make_group_with_persona(handler_session):
    """
    Factory fixture: inserts a Group + Persona into the in-memory DB.

    Returns an async callable:
        group, persona = await make_group_with_persona(telegram_id=..., title=...)
    """
    async def _factory(telegram_id: int = -1001234567890, title: str = "Test Group"):
        async with handler_session() as session:
            group = Group(telegram_id=telegram_id, title=title, is_active=True)
            session.add(group)
            await session.flush()

            persona = Persona(
                group_id=group.id,
                name="Nicat",
                bio="26 yaşlı Bakılı oğlan.",
                personality="Rahat, mehriban.",
                language_style="Azərbaycanca + rus sözləri.",
                auto_message_enabled=True,
                auto_message_interval_min=45,
                auto_message_interval_max=180,
                context_window=30,
            )
            session.add(persona)
            await session.commit()

        # Re-fetch outside the session so returned objects are detached but usable
        async with handler_session() as session:
            result = await session.execute(
                select(Group).where(Group.telegram_id == telegram_id)
            )
            group = result.scalar_one()
            result2 = await session.execute(
                select(Persona).where(Persona.group_id == group.id)
            )
            persona = result2.scalar_one()

        return group, persona

    return _factory


# ---------------------------------------------------------------------------
# is_mentioned — pure function tests (no DB, no async)
# ---------------------------------------------------------------------------

def _make_message(
    text: str = "hello",
    entities: list | None = None,
    reply_to_message=None,
) -> MagicMock:
    """Build a minimal fake telegram.Message for is_mentioned tests."""
    msg = MagicMock()
    msg.text = text
    msg.entities = entities if entities is not None else []
    msg.reply_to_message = reply_to_message
    return msg


def _make_mention_entity(offset: int, length: int) -> MagicMock:
    """Build a fake MessageEntity of type MENTION."""
    entity = MagicMock()
    entity.type = MessageEntityType.MENTION
    entity.offset = offset
    entity.length = length
    return entity


def test_is_mentioned_at_username():
    """@testbot entity in message → True."""
    text = "Hey @testbot what do you think?"
    entity = _make_mention_entity(offset=4, length=8)  # "@testbot"
    msg = _make_message(text=text, entities=[entity])
    assert is_mentioned(msg, bot_username="testbot", persona_name="Nicat", bot_id=99) is True


def test_is_mentioned_persona_name_in_text():
    """Persona name present in message body → True."""
    msg = _make_message(text="Nicat, what time is it?")
    assert is_mentioned(msg, bot_username="testbot", persona_name="Nicat", bot_id=99) is True


def test_is_mentioned_reply_to_bot():
    """Direct reply to a bot message → True."""
    bot_user = MagicMock()
    bot_user.id = 99

    reply = MagicMock()
    reply.from_user = bot_user

    msg = _make_message(text="ok thanks", reply_to_message=reply)
    assert is_mentioned(msg, bot_username="testbot", persona_name="Nicat", bot_id=99) is True


def test_is_mentioned_no_match():
    """None of the three cases match → False."""
    msg = _make_message(text="just a regular message")
    msg.reply_to_message = None
    assert is_mentioned(msg, bot_username="testbot", persona_name="Nicat", bot_id=99) is False


def test_is_mentioned_username_case_insensitive():
    """@TESTBOT should match bot_username='testbot' (case-insensitive)."""
    text = "@TESTBOT are you there?"
    entity = _make_mention_entity(offset=0, length=8)  # "@TESTBOT"
    msg = _make_message(text=text, entities=[entity])
    assert is_mentioned(msg, bot_username="testbot", persona_name="Nicat", bot_id=99) is True


# ---------------------------------------------------------------------------
# save_message — async DB tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_message_stores_row(handler_session, make_group_with_persona):
    """save_message creates a row with correct field values."""
    group, _ = await make_group_with_persona(telegram_id=-1001111111111)
    sent = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    async with handler_session() as session:
        msg = await save_message(
            session,
            group_id=group.id,
            telegram_message_id=42,
            sender_id=777000,
            sender_name="Anar Həsənov",
            sender_username="anar_h",
            text="Salam dünya",
            is_bot=False,
            replied_to_id=None,
            sent_at=sent,
        )

    assert msg.id is not None
    assert msg.telegram_message_id == 42
    assert msg.sender_id == 777000
    assert msg.sender_name == "Anar Həsənov"
    assert msg.sender_username == "anar_h"
    assert msg.text == "Salam dünya"
    assert msg.is_bot is False
    assert msg.replied_to_id is None

    # Verify the row is actually in the DB
    async with handler_session() as session:
        result = await session.execute(select(Message).where(Message.id == msg.id))
        row = result.scalar_one_or_none()
    assert row is not None


@pytest.mark.asyncio
async def test_save_message_is_bot_true(handler_session, make_group_with_persona):
    """save_message stores is_bot=True correctly (for bot outgoing messages)."""
    group, _ = await make_group_with_persona(telegram_id=-1002222222222)
    sent = datetime(2024, 1, 15, 13, 0, 0, tzinfo=timezone.utc)

    async with handler_session() as session:
        msg = await save_message(
            session,
            group_id=group.id,
            telegram_message_id=101,
            sender_id=12345678,
            sender_name="MissCaddyBot",
            sender_username="misscaddybot",
            text="Necəsən?",
            is_bot=True,
            replied_to_id=100,
            sent_at=sent,
        )

    assert msg.is_bot is True
    assert msg.replied_to_id == 100


@pytest.mark.asyncio
async def test_save_message_replied_to_id_none(handler_session, make_group_with_persona):
    """save_message stores replied_to_id=None (nullable column)."""
    group, _ = await make_group_with_persona(telegram_id=-1003333333333)
    sent = datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)

    async with handler_session() as session:
        msg = await save_message(
            session,
            group_id=group.id,
            telegram_message_id=200,
            sender_id=888000,
            sender_name="Test User",
            sender_username=None,
            text="top-level message",
            is_bot=False,
            replied_to_id=None,
            sent_at=sent,
        )

    assert msg.replied_to_id is None
    assert msg.sender_username is None


# ---------------------------------------------------------------------------
# handle_message — integration tests with mocked PTB objects
# ---------------------------------------------------------------------------

def _make_update(
    chat_id: int,
    message_id: int,
    text: str,
    user_id: int = 777000,
    first_name: str = "Anar",
    last_name: str | None = None,
    username: str | None = "anar_h",
    entities: list | None = None,
    reply_to_message=None,
) -> MagicMock:
    """Build a minimal fake Update for handle_message tests."""
    user = MagicMock()
    user.id = user_id
    user.first_name = first_name
    user.last_name = last_name
    user.username = username

    message = MagicMock()
    message.text = text
    message.message_id = message_id
    message.chat_id = chat_id
    message.from_user = user
    message.date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    message.entities = entities if entities is not None else []
    message.reply_to_message = reply_to_message

    update = MagicMock()
    update.effective_message = message
    return update


def _make_context(bot_username: str = "testbot", bot_id: int = 99) -> MagicMock:
    """Build a minimal fake ContextTypes.DEFAULT_TYPE."""
    bot = MagicMock()
    bot.username = bot_username
    bot.id = bot_id

    context = MagicMock()
    context.bot = bot
    return context


@pytest.mark.asyncio
async def test_handle_message_unknown_group_no_save(handler_session):
    """
    Messages from a group not in the DB are silently skipped.
    No Message row should be written.
    """
    update = _make_update(chat_id=-9999999999, message_id=1, text="hello")
    context = _make_context()

    with patch("bot.database.AsyncSessionLocal", handler_session):
        await handle_message(update, context)

    async with handler_session() as session:
        result = await session.execute(select(Message))
        rows = result.scalars().all()
    assert len(rows) == 0, f"Expected 0 rows, got {len(rows)}"


@pytest.mark.asyncio
async def test_handle_message_saves_incoming_message(
    handler_session, make_group_with_persona
):
    """handle_message persists the incoming message with correct field values."""
    group, _ = await make_group_with_persona(telegram_id=-1004444444444)
    update = _make_update(
        chat_id=-1004444444444,
        message_id=55,
        text="Necəsən dostum?",
        user_id=123456,
        first_name="Kamran",
        last_name="Əliyev",
        username="kamran_e",
    )
    context = _make_context()

    with patch("bot.database.AsyncSessionLocal", handler_session):
        await handle_message(update, context)

    async with handler_session() as session:
        result = await session.execute(
            select(Message).where(Message.group_id == group.id)
        )
        rows = result.scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.telegram_message_id == 55
    assert row.sender_id == 123456
    assert row.sender_name == "Kamran Əliyev"
    assert row.sender_username == "kamran_e"
    assert row.text == "Necəsən dostum?"
    assert row.is_bot is False
    assert row.replied_to_id is None


@pytest.mark.asyncio
async def test_handle_message_mention_detected_logs(
    handler_session, make_group_with_persona, caplog
):
    """
    When the bot is @mentioned, handle_message logs 'Mention detected' at INFO level.
    """
    group, persona = await make_group_with_persona(telegram_id=-1005555555555)

    text = "@testbot salam"
    entity = MagicMock()
    entity.type = MessageEntityType.MENTION
    entity.offset = 0
    entity.length = 8  # "@testbot"

    update = _make_update(
        chat_id=-1005555555555,
        message_id=77,
        text=text,
        entities=[entity],
    )
    context = _make_context(bot_username="testbot", bot_id=99)

    import logging
    with patch("bot.database.AsyncSessionLocal", handler_session):
        with caplog.at_level(logging.INFO, logger="bot.handlers"):
            await handle_message(update, context)

    assert "Mention detected" in caplog.text


@pytest.mark.asyncio
async def test_handle_message_no_mention_no_log(
    handler_session, make_group_with_persona, caplog
):
    """
    When there is no mention, handle_message does NOT log 'Mention detected'.
    """
    group, _ = await make_group_with_persona(telegram_id=-1006666666666)

    update = _make_update(
        chat_id=-1006666666666,
        message_id=88,
        text="just talking to each other",
    )
    context = _make_context(bot_username="testbot", bot_id=99)

    import logging
    with patch("bot.database.AsyncSessionLocal", handler_session):
        with caplog.at_level(logging.INFO, logger="bot.handlers"):
            await handle_message(update, context)

    assert "Mention detected" not in caplog.text
