# tests/test_seed.py
"""
Tests for seed.py — Group and Persona record creation.

Imports seed.main() directly (async coroutine). Uses in-memory SQLite fixture.
Does NOT test argparse — that is CLI boilerplate, not logic.
"""
import os
import sys
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.models import Base, Group, Persona


# ---------------------------------------------------------------------------
# Fixture: isolated in-memory DB + patched AsyncSessionLocal
# ---------------------------------------------------------------------------

@pytest.fixture
async def seed_session():
    """
    Creates an in-memory SQLite engine, patches bot.database.AsyncSessionLocal
    to use it, then yields a session factory for assertions.

    DATABASE_URL must be set before bot.database is imported (it reads the env
    var at module level). We set it here so the patch() call doesn't fail.
    """
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite+aiosqlite:///:memory:"}):
        import bot.database  # ensure module is imported with DATABASE_URL set  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    with patch("bot.database.AsyncSessionLocal", factory):
        yield factory

    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def import_seed_main():
    """
    Import seed.main, bypassing the load_dotenv() + env validation at module level.
    We patch DATABASE_URL before importing so the module-level check passes.
    """
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite+aiosqlite:///:memory:"}):
        if "seed" in sys.modules:
            del sys.modules["seed"]
        import seed
        return seed.main


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seed_creates_group(seed_session):
    seed_main = import_seed_main()

    with patch("bot.database.AsyncSessionLocal", seed_session):
        await seed_main(group_id=111222333, title="My Test Group")

    async with seed_session() as session:
        result = await session.execute(
            select(Group).where(Group.telegram_id == 111222333)
        )
        group = result.scalar_one_or_none()

    assert group is not None, "Group was not created"
    assert group.telegram_id == 111222333
    assert group.title == "My Test Group"
    assert group.is_active is True


@pytest.mark.asyncio
async def test_seed_creates_persona(seed_session):
    seed_main = import_seed_main()

    with patch("bot.database.AsyncSessionLocal", seed_session):
        await seed_main(group_id=111222444, title="Another Group")

    async with seed_session() as session:
        result = await session.execute(
            select(Group).where(Group.telegram_id == 111222444)
        )
        group = result.scalar_one_or_none()
        assert group is not None

        result2 = await session.execute(
            select(Persona).where(Persona.group_id == group.id)
        )
        persona = result2.scalar_one_or_none()

    assert persona is not None, "Persona was not created"
    assert persona.name == "Nicat"
    assert persona.context_window == 30
    assert persona.auto_message_interval_min == 45
    assert persona.auto_message_interval_max == 180
    assert persona.auto_message_enabled is True


@pytest.mark.asyncio
async def test_seed_persona_bio_correct(seed_session):
    seed_main = import_seed_main()

    with patch("bot.database.AsyncSessionLocal", seed_session):
        await seed_main(group_id=111222555, title="Bio Test Group")

    async with seed_session() as session:
        result = await session.execute(
            select(Group).where(Group.telegram_id == 111222555)
        )
        group_id = result.scalar_one().id

        result2 = await session.execute(
            select(Persona).where(Persona.group_id == group_id)
        )
        persona = result2.scalar_one()

    assert "Bakılı" in persona.bio
    assert "IT" in persona.bio


@pytest.mark.asyncio
async def test_seed_idempotent_on_existing_group(seed_session, capsys):
    seed_main = import_seed_main()

    with patch("bot.database.AsyncSessionLocal", seed_session):
        await seed_main(group_id=111222666, title="Idempotent Group")
        await seed_main(group_id=111222666, title="Idempotent Group")

    async with seed_session() as session:
        group_result = await session.execute(
            select(Group).where(Group.telegram_id == 111222666)
        )
        groups = group_result.scalars().all()

        persona_result = await session.execute(select(Persona))
        personas = persona_result.scalars().all()

    assert len(groups) == 1, f"Expected 1 group, got {len(groups)}"
    group_id = groups[0].id
    group_personas = [p for p in personas if p.group_id == group_id]
    assert len(group_personas) == 1, f"Expected 1 persona, got {len(group_personas)}"

    captured = capsys.readouterr()
    assert "already exists" in captured.out or "skipping" in captured.out.lower()


@pytest.mark.asyncio
async def test_seed_prints_confirmation(seed_session, capsys):
    seed_main = import_seed_main()

    with patch("bot.database.AsyncSessionLocal", seed_session):
        await seed_main(group_id=111222777, title="Confirmation Group")

    captured = capsys.readouterr()
    assert "Confirmation Group" in captured.out
    assert "Nicat" in captured.out
