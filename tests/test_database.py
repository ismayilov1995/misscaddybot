# tests/test_database.py
"""Tests for database initialization (DEPLOY-03)."""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from bot.models import Base


async def test_init_db_creates_tables():
    """init_db() creates groups, personas, messages tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with engine.connect() as conn:
        # inspect via run_sync
        def get_table_names(sync_conn):
            return inspect(sync_conn).get_table_names()

        tables = await conn.run_sync(get_table_names)

    assert "groups" in tables, f"'groups' table missing. Found: {tables}"
    assert "personas" in tables, f"'personas' table missing. Found: {tables}"
    assert "messages" in tables, f"'messages' table missing. Found: {tables}"

    await engine.dispose()


async def test_async_sessionmaker_expire_on_commit_false():
    """AsyncSessionLocal is configured with expire_on_commit=False."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from bot.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        assert session.sync_session.expire_on_commit is False

    await engine.dispose()
