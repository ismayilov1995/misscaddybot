# Stack Research

**Domain:** Telegram persona bot — async Python, PostgreSQL persistence, LLM integration, scheduled tasks
**Researched:** 2026-04-06
**Confidence:** MEDIUM (versions pinned in requirements.txt confirmed; external tool calls blocked, so latest-version claims are from training data through August 2025)

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.11+ | Runtime | 3.11 ships significant asyncio performance improvements over 3.10. 3.12 is stable but 3.11 is the safe floor given Ubuntu 24.04 apt availability. 3.13 is available but introduces free-threaded mode changes not relevant here — stick with 3.11 for widest VPS compatibility. |
| python-telegram-bot | 21.10 (pinned) | Telegram Bot API interface | v21 is the current stable async-native release series. It ships its own Application event loop that integrates cleanly with asyncio; v13.x (sync) and earlier are end-of-life. The PTB team is the de-facto standard — no serious alternative exists in the Python ecosystem for full Bot API coverage. |
| anthropic | >=0.40.0 (floor pinned) | Claude API client | Official SDK. v0.40+ introduced the Messages API with `cache_control` support required for prompt caching. The async client (`AsyncAnthropic`) is first-class in this range. Pin a floor, not a ceiling — Anthropic releases frequently and the SDK is generally backward-compatible within minor versions. |
| SQLAlchemy | 2.0.36 (pinned) | ORM + async session management | SQLAlchemy 2.0 is a full rewrite of the ORM. The `AsyncSession` API with `asyncpg` as the driver is the standard async persistence pattern for Python in 2024–2025. The 1.x API is legacy; 2.0's `select()` style is cleaner and works uniformly with async. |
| asyncpg | 0.30.0 (pinned) | PostgreSQL async driver | The fastest pure-async PostgreSQL driver for Python. SQLAlchemy's async dialect (`postgresql+asyncpg://`) uses it directly. psycopg3 is an alternative (see below) but asyncpg has more stable production history with SQLAlchemy async. |
| APScheduler | 3.10.4 (pinned) | Scheduled auto-message jobs | See detailed note in APScheduler section below. 3.x is the correct choice for this project. |
| python-dotenv | 1.0.1 (pinned) | Environment variable loading from .env | De-facto standard for non-Docker deployments. systemd's `EnvironmentFile=` directive can replace it at the OS level, but dotenv keeps local dev/prod parity. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| alembic | ~1.13.x | Database schema migrations | Required as soon as the schema needs any change after initial deploy. Do not use `Base.metadata.create_all()` alone in production — it can't handle alterations. Add from day one to avoid manual schema surgery on the VPS. |
| pydantic | ~2.x | Settings validation | Optional but recommended for parsing and validating `.env` values (e.g., ensuring `DATABASE_URL` is a valid DSN). Works well alongside python-dotenv via `pydantic-settings`. |
| pydantic-settings | ~2.x | Typed settings from env/dotenv | Replaces ad-hoc `os.getenv()` calls with a typed `Settings` class. Especially useful when the persona config grows. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest-asyncio | Async test support | Required for testing async handlers and DB code. Set `asyncio_mode = "auto"` in `pytest.ini`. |
| pytest | Test runner | Standard. |
| black | Code formatter | Opinionated, no config needed. |
| ruff | Linter | Replaces flake8 + isort. Fast, single tool. |

---

## APScheduler: 3.x vs 4.x — Critical Decision Note

**Use APScheduler 3.x (3.10.4 as pinned). Do not upgrade to 4.x for this project.**

### Why 3.x is correct here

APScheduler 4.x is a complete API rewrite released in early 2024. As of mid-2025 it is still in release candidate / early stable status for some builds and the documentation is incomplete. More importantly:

- **3.x integrates with python-telegram-bot's event loop via `AsyncIOScheduler`** with a well-understood pattern: pass the running loop on startup, schedule jobs that call `asyncio.create_task()`. This pattern is battle-tested.
- **4.x changes the scheduler API substantially** — `AsyncScheduler` replaces `AsyncIOScheduler`, job stores and executors are redesigned, and the way you hook into an existing event loop is different. Migrating later is a defined path; starting with 4.x for a new project requires reading sparse docs.
- **3.10.4 is the final feature release of the 3.x line** — it receives security patches. No known critical bugs affect the `AsyncIOScheduler` + asyncio use case.
- **For this project's scale** (one job, random interval 45–180 min), the 3.x `AsyncIOScheduler` with `add_job(trigger='interval')` is perfectly sufficient and adds zero operational complexity.

### When to use 4.x instead

If you were building a multi-tenant system with hundreds of distinct schedules, persistent job stores (Redis/MongoDB), or needed the new datastore abstractions — 4.x is the right direction. Not applicable here.

**Confidence on this recommendation: HIGH** — the 3.x/4.x split is a well-documented breaking change. The 3.x API for asyncio is stable and the integration pattern with PTB v21 is proven.

---

## python-telegram-bot v21: Key Integration Notes

### Event loop ownership

PTB v21 owns the asyncio event loop via `Application.run_polling()`. This is important for APScheduler integration:

- Start `AsyncIOScheduler` **before** calling `run_polling()`, or use PTB's `post_init` hook on the `ApplicationBuilder` to start the scheduler after the event loop is running.
- Do **not** start the scheduler in a `__main__` block before `run_polling()` — the event loop won't be running yet when APScheduler tries to schedule coroutines.

The correct pattern:
```python
async def post_init(application: Application) -> None:
    scheduler.start()

application = (
    ApplicationBuilder()
    .token(TOKEN)
    .post_init(post_init)
    .build()
)
```

### Polling vs Webhooks

PTB v21 supports both. For this project, long-polling is the right choice:
- No public URL needed (avoids nginx/SSL complexity on the $6 droplet)
- Sufficient for 20 interactions/day
- `run_polling()` handles reconnection and error recovery automatically

### Privacy Mode

The bot must have Privacy Mode **disabled** in BotFather settings to receive all group messages (not just commands). This is a Telegram-side setting, not a code concern, but it will silently break message ingestion if forgotten.

---

## SQLAlchemy 2.0 + asyncpg: Integration Notes

### Session management pattern

Use `async_sessionmaker` (introduced in SQLAlchemy 2.0) rather than `sessionmaker` with async. The `AsyncSession` must be created per-request/per-handler call — do not share a session across handlers.

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine("postgresql+asyncpg://...", echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

### asyncpg driver note

The `DATABASE_URL` must use the `postgresql+asyncpg://` scheme — not `postgresql://` or `postgresql+psycopg2://`. SQLAlchemy will raise a clear error if you use the wrong scheme, but it's easy to paste a plain `postgresql://` URL from a tutorial.

### `expire_on_commit=False`

Set this on `async_sessionmaker`. With the default `expire_on_commit=True`, accessing ORM attributes after a `commit()` triggers a lazy-load, which is a synchronous I/O call that raises a `MissingGreenlet` error in async context. This is the #1 gotcha with SQLAlchemy async.

---

## Anthropic SDK: Prompt Caching Pattern

The `cache_control` field on system prompt blocks is available in the `anthropic>=0.40.0` SDK. The `ephemeral` cache TTL is 5 minutes. For this bot's usage pattern (messages arriving continuously during active periods), the cache will stay warm and system prompt tokens will be billed at 10% of normal input rate on cache hits.

The async client is `AsyncAnthropic`:
```python
from anthropic import AsyncAnthropic
client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
```

The model `claude-haiku-4-5-20251001` (as specified in PLAN.md) is the cost-optimized choice. Haiku is approximately 10x cheaper than Sonnet for input tokens, appropriate for high-frequency casual conversation where response quality requirements are moderate.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| python-telegram-bot v21 | aiogram v3 | If you need higher throughput (aiogram is faster, more middleware-friendly) or prefer a more explicit dependency injection pattern. For this project's scale, PTB is simpler and the documentation is more beginner-accessible. |
| asyncpg (via SQLAlchemy) | psycopg3 (asyncio) | psycopg3 has better COPY support and is the "official" PostgreSQL driver direction. Use if you need COPY streaming or prefer a single driver for sync+async. asyncpg is faster for pure async OLTP workloads. |
| APScheduler 3.10.4 | APScheduler 4.x | Only when starting a new project that can accept 4.x API churn, needs persistent job stores, or requires the new datastore abstractions. Not applicable here. |
| APScheduler 3.10.4 | Celery + Redis | Celery is appropriate for distributed task queues with multiple workers. Massive overkill for a single-process bot with one scheduled job. Adds Redis as an infrastructure dependency. |
| SQLAlchemy 2.0 async | Tortoise ORM | Tortoise was the go-to Django-style async ORM before SQLAlchemy 2.0 matured. SQLAlchemy 2.0 async is now the standard; Tortoise has slower ecosystem momentum in 2024–2025. |
| SQLAlchemy 2.0 async | raw asyncpg queries | Acceptable for very simple schemas. For this project's 3-table schema with FK relationships, the ORM adds meaningful value for context fetching queries. |
| python-dotenv | pydantic-settings alone | pydantic-settings can load `.env` directly without python-dotenv. If you add pydantic-settings, python-dotenv becomes redundant. Keep python-dotenv for simplicity unless you add pydantic-settings. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| python-telegram-bot v13.x or earlier | Synchronous API, incompatible with async handlers and asyncpg. All tutorials using `@bot.message_handler` or `Updater(token=...)` are v13 — do not follow them. | python-telegram-bot v21 |
| APScheduler 4.x | API completely rewritten, documentation incomplete as of mid-2025, integration with PTB v21's event loop requires different patterns. The 3.x → 4.x migration is a defined future path, not an upgrade to take on greenfield. | APScheduler 3.10.4 |
| psycopg2 | Synchronous driver, blocks the event loop. Using it with SQLAlchemy async produces `MissingGreenlet` errors at runtime. | asyncpg |
| `Base.metadata.create_all()` in production | Creates tables on startup but cannot handle schema changes. Any ALTER TABLE requires manual intervention. | alembic for all schema management |
| `session.execute(text("SELECT ..."))` for all queries | Bypasses ORM, losing type safety and making refactors brittle. Acceptable for one-off raw queries; not as the default pattern. | SQLAlchemy ORM query style |
| `openai` package | Not the Anthropic SDK. Claude API requires the `anthropic` package. | anthropic |
| Docker | Adds operational complexity (container management, image builds, networking) for a single-service VPS deploy. The $6 droplet's RAM is better spent on the application. systemd is the correct production supervisor here. | systemd directly |

---

## Version Compatibility Matrix

| Package | Version | Compatible With | Notes |
|---------|---------|-----------------|-------|
| python-telegram-bot | 21.10 | Python 3.8–3.12 | PTB v21 officially supports 3.8+; 3.11 recommended for performance. httpx is a transitive dependency (PTB uses it for HTTP). |
| SQLAlchemy | 2.0.36 | asyncpg 0.28+ | SQLAlchemy 2.0's asyncpg dialect is tested against asyncpg 0.27+. 0.30.0 is confirmed compatible. Do not use SQLAlchemy 1.x with asyncpg — the async extension was experimental in 1.4 and the API changed in 2.0. |
| asyncpg | 0.30.0 | Python 3.8–3.12, PostgreSQL 9.6–16 | asyncpg 0.30.x supports PostgreSQL 16. No compatibility issues with the pinned SQLAlchemy version. |
| APScheduler | 3.10.4 | Python 3.8+, asyncio | Uses `AsyncIOScheduler`. Requires the asyncio event loop to be running before `scheduler.start()` is called — use PTB's `post_init` hook. |
| anthropic | >=0.40.0 | Python 3.8+ | `cache_control` on system prompt blocks available from 0.40+. The `AsyncAnthropic` client is thread-safe. |
| python-dotenv | 1.0.1 | All above | No cross-dependency conflicts. |
| alembic | ~1.13.x (add) | SQLAlchemy 2.0.x | alembic 1.13+ fully supports SQLAlchemy 2.0 async engine configuration. Requires `async_fallback` mode or explicit sync engine in `env.py` for migration runs. |

### Critical compatibility note: alembic + async engine

Alembic migrations cannot run against an async engine directly — alembic's migration runner is synchronous. In `alembic/env.py`, configure a **synchronous** version of the connection URL (swap `postgresql+asyncpg://` for `postgresql+psycopg2://` or `postgresql://`) for the migration context, while keeping the async URL for the application. This is a known pattern and alembic's async template handles it.

---

## Stack Patterns by Variant

**If adding webhook mode later (scaling beyond one group):**
- Add nginx reverse proxy for SSL termination
- Switch `run_polling()` to `run_webhook()` with PTB's built-in webhook server
- Keep everything else the same — PTB v21 supports both modes with the same Application setup

**If adding a web admin UI later:**
- Add FastAPI (async, shares the same event loop context)
- Use the same `AsyncSessionLocal` session factory
- Do not mix Flask/Django — they are sync frameworks that would fight the async setup

**If scaling to multiple groups with different personas:**
- The DB schema already supports this (per-group Persona FK)
- APScheduler jobs need to be per-group: iterate active groups in the scheduled job rather than adding one job per group
- No stack changes required

---

## Installation

```bash
# Create virtualenv
python3.11 -m venv venv
source venv/bin/activate

# Core stack (as in requirements.txt)
pip install \
  python-telegram-bot==21.10 \
  anthropic>=0.40.0 \
  "sqlalchemy[asyncio]==2.0.36" \
  asyncpg==0.30.0 \
  apscheduler==3.10.4 \
  python-dotenv==1.0.1

# Strongly recommended additions
pip install alembic~=1.13

# Dev dependencies
pip install pytest pytest-asyncio black ruff
```

---

## Sources

- `requirements.txt` in project root — pinned versions used as ground truth (HIGH confidence)
- `PLAN.md` in project root — architectural decisions and deployment context (HIGH confidence)
- python-telegram-bot v21 documentation (docs.python-telegram-bot.org) — async Application pattern, post_init hook, polling vs webhook (MEDIUM confidence — based on training data through August 2025; external fetch blocked)
- SQLAlchemy 2.0 documentation — AsyncSession, async_sessionmaker, expire_on_commit behavior (MEDIUM confidence — well-documented breaking change from 1.x)
- APScheduler changelog — 3.x vs 4.x API differences (MEDIUM confidence — 4.x rewrite is a well-documented breaking change)
- Anthropic API documentation — cache_control on system blocks, ephemeral TTL (MEDIUM confidence — based on training data; recommend verifying current TTL and supported models at docs.anthropic.com)

**Note:** WebSearch, WebFetch, and Bash tool calls were all denied in this environment. Version claims are grounded in the project's own pinned `requirements.txt` (high confidence) and training knowledge through August 2025 (medium confidence). Before shipping, validate the following externally:
1. `pip index versions python-telegram-bot` — confirm 21.10 is not superseded by a 21.x patch with breaking changes
2. `pip index versions apscheduler` — confirm APScheduler 4.x stable release status as of build date
3. Anthropic docs — confirm `cache_control` `ephemeral` TTL is still 5 minutes and applies to Haiku models

---
*Stack research for: Telegram persona bot (async Python + PostgreSQL + LLM + scheduler)*
*Researched: 2026-04-06*
