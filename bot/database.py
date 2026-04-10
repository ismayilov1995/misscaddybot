# bot/database.py
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.models import Base

# DATABASE_URL is read from os.environ (not os.getenv) because main.py
# validates it is set before importing this module. KeyError here = a bug in main.py.
engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)

# expire_on_commit=False is REQUIRED for async SQLAlchemy.
# With the default expire_on_commit=True, accessing any ORM attribute after session.commit()
# triggers a lazy load. In async context this raises MissingGreenlet.
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


async def init_db() -> None:
    """Create all tables if they do not exist. Called once at startup via post_init hook."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
