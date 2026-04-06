# Project Research Summary

**Project:** MissCaddyBot
**Domain:** Telegram persona bot — AI human impersonation in group chat
**Researched:** 2026-04-06
**Confidence:** MEDIUM-HIGH

## Executive Summary

MissCaddyBot is a Telegram bot that impersonates a real human group member in a small, private Azerbaijani-speaking group. The core product is not a chatbot — it is a social deception system where the primary success metric is "does the group believe this is a real person?" Every technical and feature decision flows from that constraint. Research confirms the recommended approach: async Python (python-telegram-bot v21 + SQLAlchemy 2.0 async + APScheduler 3.x) deployed as a single-process systemd service on a $6 DigitalOcean droplet, with claude-haiku-4-5 as the LLM backend and prompt caching to keep API cost under $1/month.

The architecture is well-suited to this scale and has well-documented patterns. The highest-risk area is not the tech stack — it is prompt engineering. The Azerbaijani/Russian/Turkish code-switching persona must be defined with concrete dialect examples, not abstract instructions, and must include hard anti-injection and anti-disclosure guardrails from day one. The system prompt is the core product artifact; getting it right requires a native speaker review before the bot goes live.

The two most dangerous technical traps are async session lifecycle errors (SQLAlchemy `AsyncSession` misuse causes silent connection pool exhaustion) and the APScheduler/PTB event loop integration (the scheduler must start inside PTB's `post_init` hook, not before `run_polling()`). Both are easily avoided by following established patterns documented in the architecture research. The `expire_on_commit=False` setting on the session factory is a non-negotiable requirement, not an optimization.

## Key Findings

### Recommended Stack

The stack is fully pinned in `requirements.txt` and confirmed correct by research. Python 3.11+ with `python-telegram-bot==21.10` is the async-native Telegram interface; the v21 Application event loop pattern is the only correct approach — any tutorial using `Updater(token=...)` is the legacy v13 sync API and must be ignored. `SQLAlchemy==2.0.36` with `asyncpg==0.30.0` is the standard async persistence pattern; `APScheduler==3.10.4` is the correct scheduler version — version 4.x is an API rewrite with incomplete documentation and must not be used.

One important addition not in `requirements.txt`: `alembic~=1.13` should be added from day one. Using `Base.metadata.create_all()` alone cannot handle any schema changes after initial deploy, and Alembic requires a separate synchronous connection URL in its `env.py` (swap `postgresql+asyncpg://` for `postgresql://` for migrations only).

**Core technologies:**
- `python-telegram-bot==21.10`: Telegram Bot API — the async-native standard; owns the event loop via `run_polling()`
- `anthropic>=0.40.0`: Claude API client — `AsyncAnthropic` with `cache_control` on system prompt reduces cost by 10x
- `SQLAlchemy==2.0.36` + `asyncpg==0.30.0`: Async ORM + driver — `async_sessionmaker` with `expire_on_commit=False` is mandatory
- `APScheduler==3.10.4`: Scheduled auto-messages — `AsyncIOScheduler` only, started inside PTB's `post_init` hook
- `alembic~=1.13` (add): Schema migrations — required for any post-deploy schema changes; sync URL in `env.py`

### Expected Features

The feature set is driven entirely by the human impersonation objective. Features that seem helpful in a chatbot context (clarifying questions, bullet-point summaries, formal grammar) are anti-features here because they expose bot-like patterns. The distinction between table stakes (keeps the illusion from failing) and differentiators (makes the illusion succeed) is key for prioritization.

**Must have (table stakes):**
- Message ingestion — bot must "see" everything; requires Privacy Mode disabled in BotFather before first deploy
- Mention detection — covers @username, persona name in body, and reply-to-bot gestures
- Context-aware replies — last 30 messages as conversation history; configurable per persona
- Persona system in DB — language style, personality, bio encoded before first message; this gates everything
- Natural reply latency — `sendChatAction("typing")` + 1–4s random delay, always, no exceptions
- Auto-message scheduler — jittered 45–180 min intervals using same context fetch path as reactive replies
- Short reply enforcement — max_tokens cap (~80–150) + system prompt instruction for sentence-level brevity
- Hard "never admit to being a bot" system prompt instruction

**Should have (differentiators, add after v1 validates):**
- Typing-speed realism — delay proportional to reply length (chars * 0.04s, capped ~8s)
- Quiet hours filter — no auto-messages 01:00–08:00 Baku time (UTC+4)
- Occasional non-reply — 10% skip on low-signal mentions (no question mark)
- Reply threading context — render `replied_to_id` chains in history for active threads
- Burst mode — 5% chance second auto-message follows 3–8 minutes later

**Defer (v2+):**
- Chat export to persona generation — import real user's messages to bootstrap persona
- Admin dashboard — direct DB edits are sufficient for v1
- Multi-group, multi-persona — schema already supports it; the operational complexity is not needed yet
- Long-term episodic memory — separate memory layer, not needed for 6-person group at this scale

### Architecture Approach

The architecture is a single-process async Python application where PTB v21 owns the asyncio event loop and all other components attach to it. The composition root (`main.py`) wires everything; all other modules export pure functions. The `bot/` package is split into focused modules: `config.py` → `models.py` → `database.py` → `memory.py` → `ai.py` → `handlers.py` / `scheduler.py`, in that build order. This layering means each module can be tested in isolation — `ai.py` requires no DB, `memory.py` requires no Claude calls.

**Major components:**
1. `main.py` — composition root; wires Application, registers handlers, starts scheduler in `post_init`
2. `bot/handlers.py` — PTB MessageHandler; ingests every message; detects mentions; orchestrates memory + AI
3. `bot/scheduler.py` — `AsyncIOScheduler` job definition; autonomous message generation; reschedules with fresh random interval after each run
4. `bot/memory.py` — all async DB operations (session-per-operation pattern); no business logic
5. `bot/ai.py` — prompt builder (testable, pure function) + Anthropic API call with `cache_control`
6. `bot/models.py` — SQLAlchemy ORM: `Group`, `Persona`, `Message` tables; `Message.group_id` needs composite index `(group_id, sent_at DESC)`

### Critical Pitfalls

1. **Async DB session scoping** — never pass a bare `AsyncSession` between functions or store one at module level; use `async with AsyncSessionLocal() as session:` per operation; shared sessions corrupt transaction state under concurrent handlers. Set `expire_on_commit=False` or all post-commit attribute access raises `MissingGreenlet`.

2. **APScheduler event loop conflict** — call `scheduler.start()` inside PTB's `post_init` hook, never before `run_polling()`; PTB creates its own event loop via `asyncio.run()` internally; starting the scheduler first attaches it to a different or non-existent loop, causing silent job failures.

3. **Privacy Mode not disabled** — Telegram bots receive only commands by default; Privacy Mode must be disabled in BotFather before adding the bot to the group; test by verifying the `messages` table fills from plain group conversation, not just from commands.

4. **Claude API errors drop silently** — PTB catches unhandled exceptions but the user sees no reply; wrap every `client.messages.create()` call with explicit `RateLimitError` / `APIConnectionError` / `APIStatusError` handling; returning `None` on error is correct behavior for auto-messages, but reactive replies may warrant a static fallback.

5. **Prompt injection breaks persona** — group members may send "ignore all instructions" style messages; never concatenate user input into the system prompt; always use the structured `messages` array with `role: user` / `role: assistant`; add explicit anti-disclosure instructions in the persona system prompt.

## Implications for Roadmap

Based on research, the dependency graph is clear: message ingestion and the persona system are root dependencies for everything else. The LLM layer is independent of the scheduler. Reactive replies must work before autonomous ones. Infrastructure must be solid before persona quality can be validated.

### Phase 1: Core Infrastructure and Reactive Bot

**Rationale:** Message ingestion is the root dependency for all context-aware features. The DB schema, session factory, and `ai.py` prompt builder must exist before any handler can send a meaningful reply. Privacy Mode and the `expire_on_commit=False` setting must be established here — both are silent failures that masquerade as working code.

**Delivers:** A bot that reads all group messages, detects mentions, fetches 30-message context, and replies in-persona with natural typing delay.

**Addresses:** Message ingestion, mention detection, context-aware replies, persona system in DB, natural reply latency, short reply enforcement, language/dialect prompt design, "never admit bot" instruction.

**Avoids:** Async session leaks (session-per-operation from day one), `expire_on_commit` lazy load errors, prompt injection (structured messages array from day one), Privacy Mode deployment trap.

### Phase 2: Autonomous Messaging and Production Stability

**Rationale:** Auto-messages require the context-fetch path from Phase 1 to be working. The APScheduler/PTB event loop integration is a discrete problem best tackled after the reactive path is stable. systemd deployment and flood control belong here because they validate production behavior, not dev behavior.

**Delivers:** Bot sends spontaneous contextually-relevant messages at jittered 45–180 min intervals; runs as a stable systemd service; handles Telegram rate limits gracefully.

**Addresses:** Auto-message scheduler, quiet hours, systemd deployment, flood control (RetryAfter handling).

**Avoids:** APScheduler event loop conflict (`post_init` hook), stale context in scheduler (commit before rescheduling), systemd restart loop (`StartLimitBurst=3`), Telegram flood ban.

### Phase 3: Persona Refinement and Human Texture

**Rationale:** These features improve believability but have no hard technical dependencies on Phase 2. They require the bot to be live and observed in production to calibrate correctly — typing speed realism, skip rates, and burst timing all need empirical tuning against real group behavior.

**Delivers:** Enhanced human texture: reply delay proportional to length, occasional non-reply (10% skip on low-signal mentions), burst mode (5% double auto-message), reply threading context in history.

**Addresses:** Typing-speed realism, occasional non-reply, burst mode, reply threading (`replied_to_id` in context), active hours enforcement.

**Avoids:** Over-tuning before production data; probabilistic behaviors that read as unreliable if miscalibrated.

### Phase Ordering Rationale

- Message ingestion must precede all context-aware features — it is the literal root of the dependency graph
- Persona system must be defined before the first reply — without it, Claude defaults to generic assistant behavior and the group immediately identifies the bot
- Reactive replies must work before autonomous ones — the auto-message scheduler reuses the same context-fetch and Claude-call path; validating it on reactive replies first isolates bugs
- systemd and flood control belong in Phase 2, not Phase 1 — dev-only polling is sufficient to validate the core reply loop; production hardening is a second step
- Human texture features (Phase 3) require production observation to calibrate — starting values (10% skip rate, 5% burst rate) are estimates that need real group data to tune

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3:** Baku dialect prompt engineering — the specific Russian/Turkish code-switching patterns need native speaker validation before finalizing the system prompt; training data on South Caucasus dialect specifics is MEDIUM confidence only
- **Phase 3:** Probabilistic behavior calibration (skip rate, burst frequency) — no published research on optimal values; these must be tuned empirically against real group response

Phases with standard patterns (skip research-phase):
- **Phase 1:** PTB v21 + SQLAlchemy 2.0 async + Anthropic SDK patterns are fully documented and covered in ARCHITECTURE.md — no additional research needed
- **Phase 2:** APScheduler 3.x `post_init` integration and systemd configuration are well-documented and covered in PITFALLS.md — follow the established patterns directly

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions pinned in `requirements.txt` as ground truth; 3.x vs 4.x APScheduler split is well-documented; main uncertainty is whether external version indexes have changed since August 2025 — validate with `pip index versions` before first install |
| Features | MEDIUM | Telegram API capabilities and LLM prompt engineering for persona: HIGH. Human impersonation behavioral patterns (what read as bot): MEDIUM. Specific Baku dialect patterns: MEDIUM — requires native speaker validation |
| Architecture | HIGH | PTB v21, SQLAlchemy 2.0 async, APScheduler 3.x are all stable, within knowledge window, and confirmed against pinned versions. Event loop integration pattern is battle-tested. |
| Pitfalls | HIGH | Stack-specific pitfalls are cross-verified against library internals and known production failure modes. Session lifecycle, event loop, and Privacy Mode pitfalls are deterministic and reproducible. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **Baku dialect prompt examples:** The system prompt's language style section needs concrete Azerbaijani/Russian/Turkish code-switching examples validated by a native Baku speaker before the bot goes live. Training data covers this at MEDIUM confidence — wrong examples will make the bot sound foreign rather than local.
- **`cache_control` TTL and Haiku model support:** Anthropic's prompt caching documentation should be verified at `docs.anthropic.com` before implementation — the 5-minute ephemeral TTL and Haiku model support are MEDIUM confidence from training data; this directly affects cost projections.
- **APScheduler 4.x stable status:** Confirm that APScheduler 3.10.4 is still the correct choice by checking whether 4.x reached stable release after August 2025. If 4.x is now stable and well-documented, the migration path is defined but not urgent.
- **Probabilistic behavior initial values:** The 10% non-reply skip rate and 5% burst rate are starting estimates. These need empirical calibration after 1–2 weeks of live operation in the actual group.

## Sources

### Primary (HIGH confidence)
- `/Users/ismayilismayilov/Projects/misscaddybot/requirements.txt` — pinned version ground truth for all stack decisions
- `/Users/ismayilismayilov/Projects/misscaddybot/PLAN.md` — architectural decisions, deployment context, persona spec
- PTB v21 source and changelog (github.com/python-telegram-bot) — lifecycle API, `post_init` hook, polling vs webhook
- SQLAlchemy 2.0 async documentation — `AsyncSession`, `async_sessionmaker`, `expire_on_commit` behavior

### Secondary (MEDIUM confidence)
- APScheduler 3.x documentation — `AsyncIOScheduler` event loop acquisition behavior
- Anthropic prompt caching documentation — `cache_control` ephemeral pattern, Haiku model support
- Telegram Bot API documentation — Privacy Mode, flood control (HTTP 429 RetryAfter), group message delivery
- Domain synthesis: human impersonation behavioral patterns, bot detection signals in group chat

### Tertiary (MEDIUM confidence — validate before use)
- Azerbaijani/Baku dialect code-switching patterns — from linguistic training data; needs native speaker review
- Probabilistic behavior calibration values (skip rates, burst frequency) — estimated from general principles, not empirical data

---
*Research completed: 2026-04-06*
*Ready for roadmap: yes*
