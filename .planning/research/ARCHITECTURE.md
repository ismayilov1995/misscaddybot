# Architecture Research

**Domain:** Async Python Telegram bot with LLM backend and scheduled autonomous messaging
**Researched:** 2026-04-06
**Confidence:** HIGH (PTB v21, SQLAlchemy 2.0 async, APScheduler 3.x — all stable, well-documented, within knowledge window. Exact versions confirmed from requirements.txt.)

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    External World                                 │
│  ┌─────────────────┐              ┌──────────────────────────┐   │
│  │  Telegram API   │              │   Anthropic Claude API   │   │
│  │  (polling)      │              │   (claude-haiku-4-5)     │   │
│  └────────┬────────┘              └─────────────┬────────────┘   │
└───────────┼────────────────────────────────────┼────────────────┘
            │ Updates (long-poll)                 │ LLM responses
            ▼                                     │
┌──────────────────────────────────────────────────────────────────┐
│                   Application Core (main.py)                      │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              PTB Application (event loop owner)           │   │
│  │   ApplicationBuilder → Application.run_polling()          │   │
│  │   - Owns the asyncio event loop                           │   │
│  │   - Dispatches updates to handlers via UpdaterQueue       │   │
│  │   - Lifecycle: post_init, post_shutdown hooks             │   │
│  │   - bot_data dict carries shared resources                │   │
│  └──────┬─────────────────────────────────────┬─────────────┘   │
│         │ dispatches Update                    │ shares context   │
│         ▼                                      ▼                  │
│  ┌──────────────────┐              ┌───────────────────────────┐ │
│  │  handlers.py     │              │  scheduler.py             │ │
│  │  MessageHandler  │              │  AsyncIOScheduler         │ │
│  │  - ingest msg    │              │  - started in post_init   │ │
│  │  - detect mention│              │  - job: auto_message_job  │ │
│  │  - trigger reply │              │  - reuses same event loop │ │
│  └──────┬─────────────────────────────────────┬────────────────┘ │
│         │                                      │                  │
│         └──────────────┬───────────────────────┘                  │
│                        │ both call                                │
│                        ▼                                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  memory.py  ──────────────────────────────── ai.py        │   │
│  │  DB helpers                                 Claude calls   │   │
│  │  - save_message()                           - build_prompt()│  │
│  │  - get_context()                            - get_reply()  │   │
│  │  - get_persona()                            - cache_control│   │
│  └──────┬───────────────────────────────────────────────────┘   │
│         │ async SQLAlchemy sessions                               │
└─────────┼────────────────────────────────────────────────────────┘
          ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Persistence Layer                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  PostgreSQL 16 (local)                                    │   │
│  │  models.py: Group | Persona | Message                     │   │
│  │  Engine: async_engine (asyncpg driver)                    │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `main.py` | Wire everything together; build Application; start scheduler in post_init; call run_polling | All components (composition root) |
| `bot/handlers.py` | Receive Telegram Updates; ingest every message; detect mentions; coordinate memory + ai modules | memory.py, ai.py |
| `bot/scheduler.py` | Define auto-message job function; manage AsyncIOScheduler instance | memory.py, ai.py, PTB bot object |
| `bot/memory.py` | All DB reads/writes; session lifecycle; no business logic | models.py, PostgreSQL |
| `bot/ai.py` | Build Claude prompts from persona + context; call Anthropic API; apply cache_control | Anthropic API only |
| `bot/models.py` | SQLAlchemy ORM models; no logic | Used by memory.py |
| `seed_persona.py` | One-off CLI script; creates Group + Persona rows | memory.py (or direct DB) |

---

## Critical Integration: PTB v21 + APScheduler + asyncio

This is the most architecturally sensitive part of the project. Get it wrong and you get "event loop is closed" errors or silent scheduler failures.

### How PTB v21 Owns the Event Loop

PTB v21's `Application.run_polling()` calls `asyncio.run()` internally. This means:

- **You do not create your own event loop.** PTB creates and owns it.
- `run_polling()` is blocking — it runs the loop until interrupted (SIGINT/SIGTERM).
- Everything that needs to run async must be scheduled within the loop PTB creates.

```
main.py
  └── application.run_polling()        ← asyncio.run() is called here
        └── asyncio event loop starts
              ├── Updater (long-polling Telegram)
              ├── Dispatcher (routes updates to handlers)
              └── post_init coroutine   ← scheduler starts HERE
```

### How to Start APScheduler Without Conflicting

**Wrong approach (causes RuntimeError):**
```python
# DO NOT do this — creates a second event loop
asyncio.run(main())
```

**Correct approach — use PTB's post_init hook:**
```python
async def post_init(application: Application) -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        auto_message_job,
        trigger=IntervalTrigger(minutes=random_interval()),
        kwargs={"application": application},
    )
    scheduler.start()
    application.bot_data["scheduler"] = scheduler

async def post_shutdown(application: Application) -> None:
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)

application = (
    ApplicationBuilder()
    .token(TOKEN)
    .post_init(post_init)
    .post_shutdown(post_shutdown)
    .build()
)
application.run_polling()
```

`AsyncIOScheduler` from APScheduler 3.x detects the running event loop and attaches to it automatically when `scheduler.start()` is called from within an already-running loop (which `post_init` guarantees). The job function must be `async def`.

### Random Interval Scheduling Pattern

APScheduler's `IntervalTrigger` takes a fixed interval. For variable 45–180 min intervals, reschedule after each job execution:

```python
async def auto_message_job(application: Application) -> None:
    # ... fetch context, call Claude, send message ...

    # Reschedule with new random interval
    scheduler = application.bot_data["scheduler"]
    next_minutes = random.randint(persona.auto_message_interval_min,
                                  persona.auto_message_interval_max)
    scheduler.reschedule_job(
        "auto_message",
        trigger=IntervalTrigger(minutes=next_minutes)
    )
```

Alternatively, use a `DateTrigger` with a computed next-run datetime, removed and re-added each time. Either approach is valid; reschedule_job is simpler.

---

## DB Session Lifecycle in Async Context

### The Core Rule

**Never share a SQLAlchemy async session across coroutines or across requests.** Each logical "unit of work" (one handler invocation, one scheduler job run) gets its own session, used as an async context manager, and discarded when done.

### Engine and Session Factory (created once, at startup)

```python
# bot/database.py  (or top of memory.py)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(
    DATABASE_URL,           # postgresql+asyncpg://...
    pool_size=5,
    max_overflow=10,
    echo=False,
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,   # important for async — prevents lazy-load after commit
)
```

The engine is created once when the module is imported. It manages a connection pool (asyncpg handles pooling at the driver level — SQLAlchemy's pool_size is on top of that).

### Session-Per-Operation Pattern

```python
# bot/memory.py
async def save_message(group_id: int, ...) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(Message(...))
        # commit happens on __aexit__ of session.begin()
        # session is closed and connection returned to pool

async def get_context(group_id: int, limit: int) -> list[Message]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Message)
            .where(Message.group_id == group_id)
            .order_by(Message.sent_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
```

`expire_on_commit=False` is essential in async SQLAlchemy. Without it, accessing attributes on ORM objects after `commit()` triggers lazy loads, which are synchronous and will raise `MissingGreenlet` in an async context.

### Passing the Session Factory

The `AsyncSessionLocal` factory should be accessible to both `memory.py` (import directly) and potentially passed through `application.bot_data` if you prefer dependency injection. For this project's scale, a module-level import is simpler and correct.

---

## Data Flow

### Flow 1: Inbound Message (mention → reply)

```
Telegram API (polling)
    │
    ▼ Update arrives
PTB Updater → UpdateQueue
    │
    ▼ dispatched to handler
MessageHandler.handle_message(update, context)
    │
    ├─► memory.save_message(...)          # always — store every message
    │       └─► AsyncSessionLocal() → INSERT messages
    │
    └─► if is_mention(update):
            │
            ├─► memory.get_context(group_id, limit)
            │       └─► AsyncSessionLocal() → SELECT messages
            │
            ├─► memory.get_persona(group_id)
            │       └─► AsyncSessionLocal() → SELECT persona JOIN group
            │
            ├─► ai.get_reply(persona, context_messages)
            │       └─► Anthropic API (await client.messages.create)
            │               system=[{..., "cache_control": {"type":"ephemeral"}}]
            │               messages=[...conversation history...]
            │
            ├─► await context.bot.send_message(chat_id, reply_text)
            │
            └─► memory.save_message(...)  # store bot's own reply (is_bot=True)
                    └─► AsyncSessionLocal() → INSERT messages
```

### Flow 2: Autonomous Message (scheduler-triggered)

```
APScheduler fires auto_message_job(application)
    │   (runs in PTB's event loop — no thread hopping)
    │
    ├─► memory.get_active_groups()
    │       └─► AsyncSessionLocal() → SELECT groups WHERE is_active=true
    │
    └─► for each active_group with auto_message_enabled:
            │
            ├─► memory.get_context(group_id, limit)
            ├─► memory.get_persona(group_id)
            ├─► ai.get_autonomous_message(persona, context)
            │       └─► Anthropic API (same call shape, different user instruction)
            │
            ├─► await application.bot.send_message(chat_id, text)
            │
            ├─► memory.save_message(...)  # store it
            │
            └─► scheduler.reschedule_job(...)  # randomize next interval
```

Note: The scheduler job receives the `application` object (passed as kwarg when the job is registered). This gives it access to `application.bot` for sending messages, and `application.bot_data` for the scheduler reference.

### Flow 3: Startup / Shutdown

```
main.py
    │
    └─► ApplicationBuilder().token().post_init().post_shutdown().build()
            │
            └─► application.run_polling(allowed_updates=Update.ALL_TYPES)
                    │
                    ├─► [asyncio loop starts]
                    │
                    ├─► post_init(application) called
                    │       ├─► engine created (or confirmed)
                    │       ├─► AsyncIOScheduler() started
                    │       └─► scheduler stored in bot_data
                    │
                    ├─► Updater starts polling Telegram
                    │
                    ├─► [SIGINT / SIGTERM received — systemd stop or Ctrl+C]
                    │
                    ├─► Updater stops polling
                    │
                    └─► post_shutdown(application) called
                            ├─► scheduler.shutdown(wait=False)
                            └─► await engine.dispose()
```

---

## Recommended Project Structure

```
misscaddybot/
├── main.py                      # Composition root: wire Application, scheduler, handlers
├── seed_persona.py              # CLI: create Group + Persona rows
├── requirements.txt
├── .env.example
├── systemd/
│   └── misscaddybot.service     # systemd unit
└── bot/
    ├── __init__.py
    ├── config.py                # Load .env via python-dotenv; expose typed settings
    ├── database.py              # engine + AsyncSessionLocal factory (created once)
    ├── models.py                # SQLAlchemy ORM: Base, Group, Persona, Message
    ├── memory.py                # All async DB operations (no business logic)
    ├── ai.py                    # Anthropic client, prompt builder, cache_control
    ├── handlers.py              # PTB MessageHandler, mention detection logic
    └── scheduler.py             # auto_message_job function + scheduler factory
```

**Why `database.py` is separate from `models.py`:**
`models.py` defines ORM classes — it only needs `Base`. `database.py` creates the engine and session factory — it needs the `DATABASE_URL`. Splitting them avoids circular imports when `memory.py` imports both.

**Why `config.py` is explicit:**
Scatters `os.getenv()` calls are hard to test and refactor. A single `config.py` using `python-dotenv` with typed attributes (`BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]`) makes configuration failures loud at startup rather than at first use.

---

## Architectural Patterns

### Pattern 1: Composition Root in main.py

**What:** All wiring (creating engine, building Application, registering handlers, building scheduler) happens in `main.py`. The other modules export pure functions and classes — they don't wire themselves.

**When to use:** Always for this project size. Avoids hidden coupling.

**Trade-offs:** `main.py` becomes the only file that needs to change when adding a new handler or changing the scheduler interval. All other modules stay focused.

```python
# main.py
from bot.database import engine, AsyncSessionLocal
from bot.handlers import register_handlers
from bot.scheduler import build_scheduler

async def post_init(application: Application) -> None:
    scheduler = build_scheduler(application)
    scheduler.start()
    application.bot_data["scheduler"] = scheduler

app = ApplicationBuilder().token(config.BOT_TOKEN).post_init(post_init).build()
register_handlers(app)
app.run_polling()
```

### Pattern 2: Session-Per-Operation (not session-per-request)

**What:** Each `memory.py` function opens its own session as an async context manager, performs its operation, and closes it. No session is passed between functions.

**When to use:** This project — single-process, low concurrency.

**Trade-offs:** Slightly more DB connection overhead than batching (negligible at this scale). Eliminates all session lifecycle bugs. Makes each function independently testable.

### Pattern 3: bot_data as Dependency Container

**What:** PTB's `Application.bot_data` dict holds shared long-lived resources (scheduler reference, optionally the session factory). Handler functions access them via `context.bot_data`.

**When to use:** For resources that need to be shut down gracefully (scheduler) or that handlers need access to without global imports.

**Trade-offs:** Typed access requires casting. For this project, only the scheduler goes in `bot_data`. The DB session factory is a module-level import — simpler.

### Pattern 4: Prompt Builder Separation

**What:** `ai.py` has two concerns: (1) building the prompt from persona + context messages, (2) making the API call. Keep them as separate functions.

**When to use:** Always — makes the prompt logic testable without hitting the API.

```python
# ai.py
def build_system_prompt(persona: Persona) -> str:
    return f"You are {persona.name}. {persona.personality}..."

def build_messages(context: list[Message], user_trigger: str | None) -> list[dict]:
    ...

async def get_reply(persona: Persona, context: list[Message], trigger: str) -> str:
    system_prompt = build_system_prompt(persona)
    messages = build_messages(context, trigger)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=[{"type": "text", "text": system_prompt,
                 "cache_control": {"type": "ephemeral"}}],
        messages=messages,
    )
    return response.content[0].text
```

---

## Anti-Patterns

### Anti-Pattern 1: Creating a Second Event Loop

**What people do:** Call `asyncio.run(main())` in `main.py` and start PTB inside that.

**Why it's wrong:** PTB v21's `run_polling()` calls `asyncio.run()` internally. Calling `asyncio.run()` from user code wrapping PTB will create a nested loop conflict, or worse, two separate loops where APScheduler attaches to the wrong one.

**Do this instead:** Let PTB own the loop entirely. Use `post_init` for all startup work. Only call `application.run_polling()` at the top level of `main.py` — not inside `asyncio.run()`.

### Anti-Pattern 2: Long-Lived Shared SQLAlchemy Sessions

**What people do:** Create one `AsyncSession` at startup, store it in `bot_data`, reuse it across all handlers.

**Why it's wrong:** SQLAlchemy async sessions are not thread-safe and not concurrency-safe. When two handlers run concurrently (which PTB allows), they will corrupt each other's transaction state. Connection pooling already handles reuse efficiently at a lower level.

**Do this instead:** Use `async with AsyncSessionLocal() as session:` inside each function. The session factory is cheap to call; the connection pool handles actual connection reuse.

### Anti-Pattern 3: expire_on_commit=True with Async Sessions

**What people do:** Use the default `expire_on_commit=True` (SQLAlchemy default) with async sessions.

**Why it's wrong:** After `commit()`, SQLAlchemy marks all loaded attributes as expired, expecting them to be lazily reloaded on next access. Lazy loading is synchronous and impossible in async context — raises `sqlalchemy.exc.MissingGreenlet`.

**Do this instead:** Always set `expire_on_commit=False` in the `sessionmaker` for async sessions. If you need fresh data after a commit, issue an explicit `await session.refresh(obj)`.

### Anti-Pattern 4: APScheduler Thread-Pool Executor for Async Jobs

**What people do:** Register an `async def` job with APScheduler without ensuring it's on the `AsyncIOScheduler` variant, or use `BackgroundScheduler` (which uses thread pool).

**Why it's wrong:** `BackgroundScheduler` runs jobs in threads. Calling `await` from a thread that doesn't own an event loop fails. Passing `application.bot` across thread boundaries with asyncio primitives is unsafe.

**Do this instead:** Use `AsyncIOScheduler` exclusively. It runs jobs on the existing event loop. The job function must be `async def`. Never use `BackgroundScheduler` when the rest of the app is async.

### Anti-Pattern 5: Storing DB Models Across Async Boundaries

**What people do:** Store a retrieved ORM model object (e.g., `Persona`) in `bot_data` or a module-level variable to avoid re-fetching.

**Why it's wrong:** Once the session that loaded it is closed, accessing lazy-loaded relationships raises `MissingGreenlet`. The object is also stale if the DB is updated (e.g., persona edited directly in DB).

**Do this instead:** Re-fetch the persona at the start of each handler or job that needs it. The query is simple and cheap. Alternatively, store it as a plain dataclass/dict after converting from ORM.

---

## Build Order (Dependency Graph)

Build in this order to avoid blocking on unavailable dependencies:

```
1. bot/config.py          ← no deps, needed by everything
2. bot/models.py          ← no deps (only Base + column types)
3. bot/database.py        ← needs config.py (DATABASE_URL)
4. bot/memory.py          ← needs database.py + models.py
5. bot/ai.py              ← needs config.py (ANTHROPIC_API_KEY), no DB dep
6. bot/handlers.py        ← needs memory.py + ai.py
7. bot/scheduler.py       ← needs memory.py + ai.py
8. main.py                ← needs all of the above
9. seed_persona.py        ← needs database.py + models.py (or memory.py)
```

This ordering means each phase of development can be validated in isolation:
- **models.py + database.py** can be tested with `alembic` or a direct `asyncio.run(engine.dispose())`.
- **memory.py** can be tested with a real or test DB session.
- **ai.py** can be tested by calling it directly with a fake persona dict — no DB needed.
- **handlers.py** can be tested by mocking `memory.py` and `ai.py`.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Telegram API | PTB v21 long-polling via `Application.run_polling()` | No webhook setup needed. `allowed_updates=[Update.MESSAGE]` to filter. Privacy Mode must be disabled in BotFather for group message access. |
| Anthropic Claude API | Async HTTP client (`anthropic.AsyncAnthropic`) | `cache_control: {"type": "ephemeral"}` on system prompt block on every call. Client is instantiated once and reused (it manages connection pooling internally). |
| PostgreSQL 16 | SQLAlchemy 2.0 async + asyncpg driver | `postgresql+asyncpg://` URL. asyncpg has its own connection pool; SQLAlchemy's pool sits on top. `pool_size=5` is sufficient for this scale. |

### Internal Module Boundaries

| Boundary | Communication | Rule |
|----------|---------------|------|
| handlers.py ↔ memory.py | Direct async function calls | handlers imports memory functions — no circular deps |
| handlers.py ↔ ai.py | Direct async function calls | handlers imports ai functions |
| scheduler.py ↔ memory.py | Direct async function calls | Same pattern as handlers |
| scheduler.py ↔ ai.py | Direct async function calls | Same pattern |
| memory.py ↔ models.py | SQLAlchemy ORM objects | memory creates/queries; models define schema |
| main.py ↔ scheduler.py | scheduler.py exports `build_scheduler(application)` factory | main.py calls it in post_init |
| main.py ↔ handlers.py | handlers.py exports `register_handlers(app)` | main.py calls it before run_polling |

No component except `main.py` should import from `main.py`. No circular imports.

---

## Scaling Considerations

This bot targets a single group of 6 people. Scaling notes are for context, not action.

| Scale | Architecture Adjustment |
|-------|------------------------|
| 1 group, ~20 bot interactions/day (current) | Single process, polling, local PostgreSQL — this architecture is correct and sufficient |
| 5–20 groups, ~200 bot/day | Still single process. Add `get_active_groups()` loop in scheduler. Consider DB index on `group_id + sent_at`. |
| 100+ groups | Switch from polling to webhooks. Consider task queue (Celery/arq) for Claude calls to avoid blocking PTB dispatcher. Move DB to managed service. |

**First bottleneck at current scale:** None. The $6 Droplet has excess capacity. Claude API latency (~1–2 sec) is the slowest operation, but PTB's async dispatcher handles concurrent updates without blocking.

**First bottleneck if groups scale:** Claude API calls are slow (~1-2s each). If many groups trigger simultaneously, the scheduler job loop becomes slow. Mitigation: gather() multiple Claude calls concurrently within the job.

---

## Sources

- PTB v21 source and changelog: https://github.com/python-telegram-bot/python-telegram-bot (v21.10 pinned in requirements.txt — HIGH confidence on lifecycle API)
- SQLAlchemy 2.0 async docs: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html (HIGH confidence — well-documented stable API)
- APScheduler 3.x docs: https://apscheduler.readthedocs.io/en/3.x/ (HIGH confidence on AsyncIOScheduler behavior)
- Anthropic prompt caching docs: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching (cache_control ephemeral pattern — MEDIUM confidence, feature stable since 2024)
- Note: WebSearch and WebFetch were unavailable during this research session. All findings are from training knowledge of these stable, pinned library versions. Verification against official docs recommended before implementation of the event loop integration pattern.

---
*Architecture research for: async Python Telegram bot with LLM backend (MissCaddyBot)*
*Researched: 2026-04-06*
