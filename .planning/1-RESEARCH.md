# Phase 1: Foundation — Research

**Researched:** 2026-04-07
**Domain:** SQLAlchemy 2.0 async setup, python-telegram-bot v21 Application skeleton, python-dotenv env validation
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from 1-CONTEXT.md)

### Locked Decisions

1. **Session factory location → `bot/database.py`**
   - `bot/models.py` stays pure ORM (Base + model classes only)
   - `bot/database.py` handles connectivity and exports `AsyncSessionLocal` and `engine`
   - `init_db()` (calls `Base.metadata.create_all`) lives in `bot/database.py`

2. **main.py scope → Full Telegram Application skeleton**
   - Phase 1 builds the complete `main.py` entry point including Telegram Application setup
   - Later phases add handlers without restructuring
   - Requires a real `TELEGRAM_BOT_TOKEN` to run Phase 1 success criteria check
   - `run_polling()` will connect but receive no events until handlers are added in Phase 3

3. **Startup validation → Explicit check + `sys.exit`**
   ```python
   REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "DATABASE_URL", "BOT_USERNAME"]
   for var in REQUIRED_VARS:
       if not os.getenv(var):
           sys.exit(f"ERROR: {var} is not set in .env")
   ```
   - Validation runs before DB init or Application creation
   - Exit code 1 so systemd can detect a bad-config startup failure

### What Phase 1 Does NOT Include

- No message handlers (Phase 3)
- No Claude API calls (Phase 4)
- No scheduler (Phase 5)
- No seed script (Phase 2)
- No Alembic (v2)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DEPLOY-02 | All secrets loaded from `.env` via python-dotenv | Section: python-dotenv Loading Pattern |
| DEPLOY-03 | Database schema initialized via `create_all()` on startup | Section: DB Schema Initialization |
| PERS-01 | Each Telegram group has one Persona record in DB | Section: ORM Model Design |
</phase_requirements>

---

## Summary

Phase 1 establishes the project's runnable foundation: env validation, ORM models, async DB session factory, and a Telegram Application skeleton. All four components are well-understood, use stable APIs, and have no ambiguity — this is a LOW-risk phase technically.

The single non-obvious finding is that `Application.run_polling()` in python-telegram-bot v21 is a **synchronous method** (not a coroutine) that manages its own event loop internally. The CONTEXT.md shows `await app.run_polling()` which would fail at runtime. The correct pattern for running async initialization (like `init_db()`) before polling starts is to use `ApplicationBuilder.post_init()` hook, or to call `init_db()` synchronously before `app.run_polling()` using a separate `asyncio.run()` call. See Architecture Patterns section for the verified correct approach.

The SQLAlchemy async setup, `expire_on_commit=False`, and `create_all()` via `conn.run_sync()` are all confirmed by official documentation and are straightforward to implement.

**Primary recommendation:** Use `post_init` hook to run `init_db()` inside the PTB-managed event loop, then call `app.run_polling()` from a synchronous `main()` function — not inside `asyncio.run()`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python-telegram-bot | 21.10 (pinned) | Telegram Bot API | The only full-featured async PTB library; v21 is current stable series |
| SQLAlchemy | 2.0.36 (pinned) | ORM + async session | `AsyncSession` + `async_sessionmaker` are the standard async ORM pattern |
| asyncpg | 0.30.0 (pinned) | PostgreSQL async driver | Fastest pure-async PostgreSQL driver; required by SQLAlchemy async dialect |
| python-dotenv | 1.0.1 (pinned) | `.env` file loading | De-facto standard for non-Docker VPS deployments |
| greenlet | (transitive) | SQLAlchemy async internals | Installed automatically via `sqlalchemy[asyncio]` extra |

[VERIFIED: npm registry equivalent — pip index versions confirmed SQLAlchemy 2.0.49 is latest; pinned 2.0.36 is still a supported 2.0.x release]
[VERIFIED: pip index versions confirmed asyncpg 0.31.0 is latest; pinned 0.30.0 is compatible]
[VERIFIED: pip index versions confirmed python-telegram-bot 22.5 is latest; pinned 21.10 is the most recent v21 release]

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| asyncpg | psycopg3 async | psycopg3 has better COPY support; asyncpg is faster for pure async OLTP. asyncpg is the pinned choice. |
| python-dotenv | pydantic-settings | pydantic-settings can load `.env` directly without python-dotenv; adds complexity not needed for v1. |

**Installation (virtualenv setup):**
```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Architecture Patterns

### Recommended File Structure (Phase 1)

```
misscaddybot/
├── main.py                  # Entry: env validation → init_db via post_init → run_polling
├── requirements.txt         # Already exists — pinned dependencies
├── .env.example             # Already exists — documents required vars
└── bot/
    ├── __init__.py          # Empty package marker
    ├── models.py            # DeclarativeBase subclass + Group, Persona, Message ORM classes
    └── database.py          # create_async_engine, async_sessionmaker, init_db()
```

---

### Pattern 1: SQLAlchemy Async Engine + Session Factory

**What:** Single module creates the engine and session factory; all other modules import from it.
**When to use:** Always — the engine is expensive to create and must be a singleton.

```python
# bot/database.py
# Source: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from bot.models import Base
import os

DATABASE_URL = os.environ["DATABASE_URL"]  # env already validated before this module loads

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables if they do not exist. Called once at startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

[VERIFIED: docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html — `async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)` is the documented pattern]

**Why `expire_on_commit=False`:** With the default `expire_on_commit=True`, accessing any ORM attribute after `session.commit()` triggers a lazy load. In async context this raises `MissingGreenlet: greenlet_spawn has not been called` because async SQLAlchemy cannot perform implicit I/O. Setting `expire_on_commit=False` keeps attribute values in memory after commit. [VERIFIED: docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#preventing-implicit-io-when-using-asyncsession]

---

### Pattern 2: ORM Base with AsyncAttrs Mixin

**What:** Declarative base inherits both `AsyncAttrs` and `DeclarativeBase`.
**When to use:** Always for async SQLAlchemy ORM — `AsyncAttrs` provides `awaitable_attrs` for future relationship access.

```python
# bot/models.py
# Source: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#synopsis-orm

from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from datetime import datetime


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    persona: Mapped["Persona"] = relationship("Persona", back_populates="group", uselist=False)
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="group")


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    bio: Mapped[str] = mapped_column(Text, nullable=False)
    personality: Mapped[str] = mapped_column(Text, nullable=False)
    language_style: Mapped[str] = mapped_column(Text, nullable=False)
    auto_message_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_message_interval_min: Mapped[int] = mapped_column(Integer, default=45)
    auto_message_interval_max: Mapped[int] = mapped_column(Integer, default=180)
    context_window: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    group: Mapped["Group"] = relationship("Group", back_populates="persona")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    replied_to_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    group: Mapped["Group"] = relationship("Group", back_populates="messages")
```

[VERIFIED: docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html — `AsyncAttrs, DeclarativeBase` base class pattern is documented]
[ASSUMED: `Mapped` / `mapped_column` style shown is SQLAlchemy 2.0's recommended ORM syntax — confirmed used in SQLAlchemy 2.0 docs but full model column-by-column not verified against official source]

---

### Pattern 3: PTB v21 main.py — CRITICAL: `run_polling()` is synchronous

**What:** `Application.run_polling()` in PTB v21 is a **synchronous method** (defined as `def`, not `async def`) that creates and manages its own event loop internally. It cannot be awaited and cannot be called from within a running event loop.

**Verified:** Confirmed by inspecting the PTB v21.10 source at `telegram/ext/_application.py` — `run_polling` is `def run_polling(self, ...) -> None`, not `async def`.

**Consequence for CONTEXT.md pattern:** The CONTEXT.md shows:
```python
# FROM CONTEXT.md — this will fail at runtime
async def main():
    await init_db()
    app = Application.builder().token(TOKEN).build()
    await app.run_polling()          # ERROR: run_polling is not a coroutine

if __name__ == "__main__":
    asyncio.run(main())              # ERROR: run_polling cannot be called inside asyncio.run()
```

This has two problems: (1) `await app.run_polling()` fails because it's not a coroutine, and (2) calling `run_polling()` inside `asyncio.run(main())` would trigger `RuntimeError: This event loop is already running` because `run_polling()` calls `loop.run_until_complete()` internally. [VERIFIED: github.com/python-telegram-bot/python-telegram-bot/issues/3687]

**Correct pattern:** Use `post_init` for async initialization, call `run_polling()` from synchronous `main()`:

```python
# main.py — CORRECT pattern for PTB v21 + async DB init
# Source: python-telegram-bot v21 docs — ApplicationBuilder.post_init()

import os
import sys
import logging
from dotenv import load_dotenv
from telegram.ext import Application

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "DATABASE_URL", "BOT_USERNAME"]
for var in REQUIRED_VARS:
    if not os.getenv(var):
        sys.exit(f"ERROR: {var} is not set in .env")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


async def post_init(application: Application) -> None:
    """Called by run_polling() after initialize(), before start_polling() — runs inside the PTB event loop."""
    from bot.database import init_db
    await init_db()
    logger.info("Database initialized")


def main() -> None:
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    # Handlers registered here in Phase 3
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
```

[VERIFIED: github.com/python-telegram-bot/python-telegram-bot/blob/v21.10/examples/echobot.py — `def main()` (not async) calling `application.run_polling()` directly]
[VERIFIED: ApplicationBuilder.post_init() documented at docs.python-telegram-bot.org/en/v21.10/ — executes after `initialize()` but before `start_polling()`]

---

### Pattern 4: python-dotenv Loading Order

**What:** `load_dotenv()` must be called BEFORE any `os.getenv()` or `os.environ` access. It only populates environment variables that are not already set (safe: won't override real environment variables in production).

```python
# main.py top — must be before any other imports that read os.environ
from dotenv import load_dotenv
load_dotenv()  # reads .env file if present; no-op if .env absent (deployment uses real env vars)
```

[VERIFIED: github.com/theskumar/python-dotenv — default behavior confirmed: does not override existing env vars; silent no-op if file missing]

**Key property for systemd deployment:** When running under systemd with `EnvironmentFile=/path/to/.env` in the service unit, real environment variables are already set before the process starts. `load_dotenv()` with default `override=False` will not overwrite them — correct behavior for both dev (reads .env) and production (reads systemd EnvironmentFile).

---

### Anti-Patterns to Avoid

- **`await app.run_polling()`** — `run_polling()` is not a coroutine. This raises `TypeError` at runtime.
- **`asyncio.run(main())` where `main()` calls `run_polling()`** — `run_polling()` calls `loop.run_until_complete()` internally; calling it when a loop is already running raises `RuntimeError`.
- **`Base.metadata.create_all(engine)` (sync)** — raises `MissingGreenlet` when called with an async engine. Use `async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)`.
- **Module-level `DATABASE_URL = os.environ["DATABASE_URL"]` in `bot/database.py` before `load_dotenv()`** — `os.environ["DATABASE_URL"]` raises `KeyError` if `load_dotenv()` hasn't run yet. Either import `bot.database` after `load_dotenv()`, or use `os.getenv("DATABASE_URL")` with a late-binding pattern.
- **Sharing a single `AsyncSession` instance** — `AsyncSession` is not concurrency-safe. Always create per-request via the factory.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async schema creation | Custom DDL coroutine | `async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)` | The `run_sync()` wrapper handles greenlet context correctly |
| Async session factory | Manual session lifecycle | `async_sessionmaker(engine, expire_on_commit=False)` | Factory handles cleanup, transaction scope, connection return |
| Event loop management | `asyncio.run()` wrapper around PTB | `Application.run_polling()` | PTB manages its own event loop with signal handling and graceful shutdown |
| Pre-polling async init | `asyncio.run(init_db())` before `run_polling()` | `ApplicationBuilder().post_init(init_db_callback)` | `post_init` runs inside PTB's event loop after `initialize()` |
| Env var validation | Custom config class | `os.getenv()` + `sys.exit()` loop | Simple, readable, correct exit code for systemd |

---

## Common Pitfalls

### Pitfall 1: `await app.run_polling()` — TypeError at runtime

**What goes wrong:** `run_polling()` is a sync method in PTB v21. Writing `await app.run_polling()` raises `TypeError: object NoneType can't be used in 'await' expression` (or similar) immediately.
**Why it happens:** Developers assume all PTB v21 public methods are async because the bot itself is async. `run_polling()` is the exception — it manages the event loop, so it must be synchronous.
**How to avoid:** Call `app.run_polling()` without `await`, from a `def main()` (not `async def main()`).
**Warning signs:** `TypeError` on the `run_polling()` line at startup.

---

### Pitfall 2: Calling `run_polling()` Inside `asyncio.run()`

**What goes wrong:** Wrapping a `main()` function with `asyncio.run()` then calling `run_polling()` inside it raises `RuntimeError: This event loop is already running`.
**Why it happens:** `run_polling()` calls `loop.run_until_complete()` internally. This cannot be nested inside an already-running loop.
**How to avoid:** Do not wrap the `main()` that calls `run_polling()` in `asyncio.run()`. The `if __name__ == "__main__": main()` block should call the synchronous `main()` directly.
**Warning signs:** `RuntimeError: This event loop is already running` on startup.

---

### Pitfall 3: `Base.metadata.create_all(engine)` With Async Engine

**What goes wrong:** Calling the synchronous `create_all(bind=engine)` with an `AsyncEngine` object raises a greenlet-related error or `MissingGreenlet`.
**Why it happens:** `create_all()` is synchronous; async engine cannot execute synchronous I/O outside a greenlet context.
**How to avoid:** Use `async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)`. The `run_sync()` call wraps sync execution in a greenlet context.
**Warning signs:** Error at startup mentioning `greenlet` or `MissingGreenlet` during table creation.

---

### Pitfall 4: Module-Level `os.environ["DATABASE_URL"]` Before `load_dotenv()`

**What goes wrong:** `bot/database.py` reads `os.environ["DATABASE_URL"]` at module import time (top of file). If this module is imported before `load_dotenv()` runs in `main.py`, the variable isn't set yet → `KeyError`.
**Why it happens:** Python executes module-level code at import time. If `main.py` does `from bot.database import init_db` before calling `load_dotenv()`, the `DATABASE_URL` read fails.
**How to avoid:** Call `load_dotenv()` at the very top of `main.py`, before any project imports. Or read `DATABASE_URL` lazily inside `init_db()` rather than at module level.
**Warning signs:** `KeyError: 'DATABASE_URL'` at startup even though `.env` has the variable.

---

### Pitfall 5: `expire_on_commit=True` (Default) → MissingGreenlet

**What goes wrong:** Default `expire_on_commit=True` means after any `session.commit()`, all loaded ORM attributes are expired. Accessing `obj.field` after commit triggers a lazy load, which SQLAlchemy async cannot do → `MissingGreenlet: greenlet_spawn has not been called`.
**Why it happens:** Works transparently in synchronous SQLAlchemy; breaks in async because there's no implicit I/O pathway.
**How to avoid:** Set `expire_on_commit=False` on `async_sessionmaker`. Phase 1 does this per the locked decisions.
**Warning signs:** `MissingGreenlet` or `greenlet_spawn` errors after any `session.commit()` call when accessing object attributes.

---

### Pitfall 6: Database URL Scheme Mismatch

**What goes wrong:** `.env` contains `DATABASE_URL=postgresql://...` (without `+asyncpg`). SQLAlchemy raises a clear error about the wrong dialect, but it can confuse developers who copy-paste URLs from tutorials.
**Why it happens:** Most PostgreSQL tutorials show plain `postgresql://` which uses psycopg2 (sync). The async setup requires `postgresql+asyncpg://`.
**How to avoid:** Ensure `.env.example` documents the correct scheme: `postgresql+asyncpg://user:password@localhost:5432/misscaddybot`. Already correct in the project's `.env.example`.
**Warning signs:** `sqlalchemy.exc.NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgresql` or similar at startup.

---

## Code Examples

### Complete `bot/database.py`

```python
# Source: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from bot.models import Base

engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

### Session Usage Pattern (for later phases)

```python
# Correct per-handler session scoping — never share sessions
async def some_handler(update, context):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # all DB work here
            result = await session.execute(select(Message).where(...))
    # session closed, connection returned to pool
```

### Env Validation Pattern (from CONTEXT.md — confirmed correct)

```python
# Source: CONTEXT.md locked decision — confirmed pattern
REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "DATABASE_URL", "BOT_USERNAME"]
for var in REQUIRED_VARS:
    if not os.getenv(var):
        sys.exit(f"ERROR: {var} is not set in .env")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `sessionmaker` with `AsyncSession` class= | `async_sessionmaker` factory | SQLAlchemy 2.0 (2023) | `async_sessionmaker` is the 2.0-native API; `sessionmaker(class_=AsyncSession)` still works but is deprecated style |
| `declarative_base()` function | `class Base(DeclarativeBase): pass` | SQLAlchemy 2.0 (2023) | New ORM style with full type annotation support via `Mapped` / `mapped_column` |
| `Column(Integer, ...)` | `mapped_column(Integer, ...)` with `Mapped[int]` | SQLAlchemy 2.0 (2023) | Type-annotated style; `Column` still works but is legacy |
| PTB v13 `Updater(token=...).start_polling()` | PTB v21 `Application.builder().token().build()` + `run_polling()` | PTB v20 (2022) | Complete API rewrite; v13 tutorials are wrong for v21 |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `onupdate=func.now()` works correctly with asyncpg for `Persona.updated_at` | ORM Model Design | `updated_at` may not auto-update; will need to set manually or use a trigger |
| A2 | `allowed_updates=["message"]` in `run_polling()` is sufficient for Phase 1 (no events expected) | Pattern 3 | Low risk — no handlers registered yet, any value works |
| A3 | Python 3.11's `str | None` union type syntax works with SQLAlchemy 2.0's `Mapped` in the target deployment environment | ORM Model Design | Must use `Optional[str]` instead on Python < 3.10 — but project requires 3.11+ so low risk |

---

## Open Questions

1. **`asyncio.run()` approach for `init_db()` as alternative**
   - What we know: The `post_init` hook is the PTB-native way. An alternative is `asyncio.run(init_db())` before calling `main()` in `__main__`.
   - What's unclear: Both are valid; `post_init` is cleaner because it runs in the same event loop PTB will use.
   - Recommendation: Use `post_init` — it is the official PTB pattern for async pre-startup initialization and avoids creating a throw-away event loop.

2. **`context_window` default value discrepancy**
   - What we know: PLAN.md says default 30; REQUIREMENTS.md says default 30; but `Persona.context_window` in PLAN.md schema says 50.
   - What's unclear: Which value is canonical for the DB column default?
   - Recommendation: Use 30 (matches requirements spec and PLAN.md prose); the DB column value in PLAN.md schema appears to be a typo.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | All code | ✓ | 3.11.x at `/opt/homebrew/bin/python3.11` | — |
| PostgreSQL | Database | ✓ | 17.9 (Homebrew) — accepting connections at port 5432 | — |
| pip / venv | Package install | ✓ | pip 21.2.4 on system python; 3.11 pip available via python3.11 -m pip | — |

**Note:** System default `python3` is 3.9.6 (macOS system Python). Always invoke as `python3.11` or activate a venv for this project. The VPS target is Python 3.11+ on Ubuntu 24.04.

**Missing dependencies with no fallback:** None — all required runtime components are present.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (not yet installed) |
| Config file | `pytest.ini` — Wave 0 gap |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DEPLOY-02 | Secrets loaded from `.env`, `sys.exit` on missing var | unit | `pytest tests/test_startup.py::test_missing_var_exits -x` | ❌ Wave 0 |
| DEPLOY-03 | `init_db()` creates all three tables | integration | `pytest tests/test_database.py::test_init_db_creates_tables -x` | ❌ Wave 0 |
| PERS-01 | `Persona` model has correct columns and FK to `Group` | unit | `pytest tests/test_models.py::test_persona_schema -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/__init__.py` — package marker
- [ ] `tests/conftest.py` — shared async DB fixtures (in-memory SQLite+aiosqlite for unit tests)
- [ ] `tests/test_startup.py` — covers DEPLOY-02 (env validation)
- [ ] `tests/test_database.py` — covers DEPLOY-03 (init_db creates tables)
- [ ] `tests/test_models.py` — covers PERS-01 (model schema)
- [ ] `pytest.ini` — `asyncio_mode = auto` required for `pytest-asyncio`
- [ ] Framework install: `pip install pytest pytest-asyncio aiosqlite` — none installed in venv yet

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A — no user auth in this phase |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A |
| V5 Input Validation | Partial | Env var presence validated via `sys.exit` loop |
| V6 Cryptography | No | Secrets read from env — never generated here |

### Known Threat Patterns for Phase 1

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| `.env` file world-readable | Info Disclosure | `chmod 600 .env` — doc in deploy checklist |
| `DATABASE_URL` logged on error | Info Disclosure | Never log `DATABASE_URL`; log "DB connected" only |
| Bot token in traceback | Info Disclosure | Set `httpx` and `telegram` log levels to WARNING in production |

---

## Sources

### Primary (HIGH confidence)
- `https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html` — `create_async_engine`, `async_sessionmaker`, `expire_on_commit=False`, `conn.run_sync()`, `AsyncAttrs` mixin, MissingGreenlet prevention
- `https://github.com/python-telegram-bot/python-telegram-bot/blob/v21.10/telegram/ext/_application.py` — confirmed `run_polling` is `def` (sync), not `async def`
- `https://github.com/python-telegram-bot/python-telegram-bot/blob/v21.10/examples/echobot.py` — canonical `def main()` + `application.run_polling()` pattern
- `.planning/research/STACK.md` — pre-researched stack analysis (HIGH confidence, verified against this session)
- `.planning/research/PITFALLS.md` — pre-researched pitfall analysis (HIGH confidence)

### Secondary (MEDIUM confidence)
- `https://python-telegram-bot.readthedocs.io` — ApplicationBuilder.post_init() callback runs after `initialize()` before `start_polling()`
- `pip index versions` output — confirmed package version availability (SQLAlchemy 2.0.49 latest, asyncpg 0.31.0 latest, PTB 22.5 latest; pinned versions remain valid)
- `https://github.com/theskumar/python-dotenv` — `load_dotenv()` default no-override behavior, `.env` absent is silent no-op

### Tertiary (LOW confidence / ASSUMED)
- `onupdate=func.now()` behavior with asyncpg — assumed from training knowledge; not verified against asyncpg-specific behavior in this session

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions confirmed via `pip index versions`; packages are pinned in `requirements.txt`
- Architecture patterns: HIGH — SQLAlchemy async pattern verified via official docs; PTB `run_polling` sync nature verified via source code inspection
- PTB entry point: HIGH — `run_polling` is sync confirmed; `post_init` hook confirmed for async pre-startup init
- Pitfalls: HIGH — `run_polling` TypeError and RuntimeError are definitive; MissingGreenlet fix is documented in official SQLAlchemy async docs
- ORM model schema: MEDIUM — column types and relationships are standard SQLAlchemy 2.0; `onupdate` behavior with asyncpg is ASSUMED

**Research date:** 2026-04-07
**Valid until:** 2026-06-07 (stable libraries — 60 days)
