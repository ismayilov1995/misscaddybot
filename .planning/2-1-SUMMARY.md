---
phase: 2
plan: 1
subsystem: ai
tags: [claude, anthropic, persona, system-prompt, async]
dependency_graph:
  requires: [bot/models.py, bot/database.py]
  provides: [bot/ai.py, seed.py]
  affects: []
tech_stack:
  added: [anthropic>=0.40.0]
  patterns: [ephemeral prompt caching, async client per call, None-on-recoverable-error]
key_files:
  created: [bot/ai.py, seed.py, tests/test_ai.py, tests/test_seed.py]
  modified: []
decisions:
  - make_persona test helper uses Persona() constructor (not __new__) to satisfy SQLAlchemy ORM state initialization
  - seed_session fixture pre-imports bot.database under DATABASE_URL env patch so patch() call does not fail on module-level KeyError
metrics:
  duration: 168s
  completed: 2026-04-07T12:16:03Z
  tasks_completed: 3
  files_created: 4
---

# Phase 2 Plan 1: Persona System Summary

Claude system prompt is constructed from a Persona ORM record via a pure function, and an async reply generator wraps the Anthropic API with ephemeral prompt caching and recoverable error handling returning None.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Create bot/ai.py — build_system_prompt + generate_reply | e00c13b |
| 2 | Create seed.py — Group and default Persona seeder | 81704b6 |
| 3 | Create tests/test_ai.py and tests/test_seed.py | bc63a83 |

## What Was Built

**bot/ai.py**
- `build_system_prompt(persona)` — pure function, zero I/O, produces an Azerbaijani human-voice persona profile with hard "never identify as bot" and short-reply rules
- `generate_reply(persona, context_messages)` — async, creates `AsyncAnthropic()` client per call (no module-level state), uses `system=[{..., "cache_control": {"type": "ephemeral"}}]` list form for prompt caching, `max_tokens=150`, returns `None` on `RateLimitError`/`APIConnectionError`/`APIStatusError`

**seed.py**
- CLI script: `python seed.py --group-id INT --title STR`
- Creates `Group` + `Persona` in a single transaction using `session.flush()` for id assignment before commit
- Idempotent: re-running on existing group-id prints "already exists, skipping." and returns without error
- Default persona "Nicat": 26-year-old Baku software worker, Azerbaijani with Russian loanwords mixed in

**tests/test_ai.py** — 16 tests
- 10 pure-function tests for `build_system_prompt` (name, bio, personality, language_style, no-bot rule, short-reply rule, return type, length, name variation, no English chatbot framing)
- 6 async mock tests for `generate_reply` (RateLimitError→None, APIConnectionError→None, APIStatusError→None, success→text, ephemeral cache_control verified, max_tokens=150 verified)

**tests/test_seed.py** — 5 tests
- In-memory SQLite fixture with `async_sessionmaker`, patches `bot.database.AsyncSessionLocal`
- Covers: group created, persona created with correct defaults, bio content, idempotency, confirmation output

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] make_persona used Persona.__new__ bypassing ORM state initialization**
- Found during: Task 3 (first test run)
- Issue: `Persona.__new__(Persona)` + `__dict__.update(...)` sets raw dict keys but SQLAlchemy's `InstrumentedAttribute.__get__` checks `self.impl.supports_population` which is `None` on uninitialized instances, raising `AttributeError`
- Fix: Changed `make_persona` to use `Persona(**defaults)` — the normal constructor initializes the ORM instance state manager correctly
- Files modified: tests/test_ai.py
- Commit: bc63a83

**2. [Rule 1 - Bug] seed_session fixture triggered bot.database import without DATABASE_URL set**
- Found during: Task 3 (first test run)
- Issue: `patch("bot.database.AsyncSessionLocal", factory)` causes `bot.database` module import, which executes `os.environ["DATABASE_URL"]` at module level — raises `KeyError` when env var is absent in test environment
- Fix: Added `patch.dict(os.environ, {"DATABASE_URL": "..."})` block in fixture before the `patch()` call, with an explicit `import bot.database` to ensure the module is loaded while the env var is set
- Files modified: tests/test_seed.py
- Commit: bc63a83

## Known Stubs

None — all persona data is wired to the DB record. `build_system_prompt` interpolates live `Persona` fields. `seed.py` writes real data.

## Threat Flags

None — no new network endpoints, auth paths, or file access patterns introduced. `generate_reply` reads `ANTHROPIC_API_KEY` from environment via `AsyncAnthropic()` default behavior; the key is never logged or returned.

## Self-Check: PASSED

- bot/ai.py exists: FOUND
- seed.py exists: FOUND
- tests/test_ai.py exists: FOUND
- tests/test_seed.py exists: FOUND
- Commit e00c13b exists: FOUND
- Commit 81704b6 exists: FOUND
- Commit bc63a83 exists: FOUND
- All 21 tests pass: CONFIRMED
