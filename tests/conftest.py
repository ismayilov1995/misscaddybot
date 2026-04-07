# tests/conftest.py
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.models import Base


@pytest.fixture
async def async_engine():
    """In-memory SQLite engine for tests. Created and torn down per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    """Async session scoped to one test."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
