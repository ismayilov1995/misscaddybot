---
phase: 3
plan: 1
subsystem: handlers
tags: [telegram, ptb, message-persistence, mention-detection, async]
dependency_graph:
  requires: [bot/models.py, bot/database.py]
  provides: [bot/handlers.py]
  affects: [main.py]
tech_stack:
  added: [aiosqlite (test-only)]
  patterns: [selectinload, in-function import, pure-function mention detection]
key_files:
  created: [bot/handlers.py, tests/test_handlers.py]
  modified: [main.py]
decisions:
  - AsyncSessionLocal imported inside handle_message function body (not at module level) to avoid KeyError on DATABASE_URL before load_dotenv() runs — same pattern as post_init in main.py
  - selectinload(Group.persona) used over joinedload to avoid cartesian-product issues on potential one-to-many relationships
  - is_mentioned is a pure sync function with no I/O — safe to call after session is closed because selectinload + expire_on_commit=False ensures persona.name is accessible without lazy-load
metrics:
  duration: 132s
  completed: 2026-04-07T12:51:07Z
  tasks_completed: 3
  files_created: 2
---

# Phase 3 Plan 1: Message Persistence & Mention Detection Summary

Every plain group text message is now persisted to the `messages` table via a PTB `MessageHandler`, and the bot can detect when it is being addressed via @username entity, persona name in text, or direct reply to a bot message.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Create bot/handlers.py — get_group_with_persona, save_message, is_mentioned, handle_message | 5e58672 |
| 2 | Update main.py — register MessageHandler for TEXT & GROUPS | 8657b45 |
| 3 | Create tests/test_handlers.py — 12 tests for all handler components | 7c95176 |

## What Was Built

**bot/handlers.py**

- `get_group_with_persona(session, telegram_id)` — async, queries Group by Telegram chat ID with `selectinload(Group.persona)`, returns `(Group, Persona)` tuple or `None` for unregistered groups
- `save_message(session, ...)` — async, persists one `Message` row and returns the ORM object; attributes remain accessible after commit due to `expire_on_commit=False` on `AsyncSessionLocal`
- `is_mentioned(message, bot_username, persona_name, bot_id)` — pure sync function, checks 3 cases: @username entity (case-insensitive), persona name substring in message body, direct reply to a bot message
- `handle_message(update, context)` — PTB `MessageHandler` coroutine; guards on `None` text/message, looks up group (silent skip if unregistered), builds sender metadata (handles missing last name via `filter(None, ...)`), saves incoming message with `is_bot=False`, logs at INFO if mention detected

**main.py** (two targeted edits)

- Extended import: `Application, MessageHandler, filters` from `telegram.ext`
- Replaced handler placeholder comment with: `app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, handle_message))`

**tests/test_handlers.py** — 12 tests

- 5 pure-function `is_mentioned` tests: @username entity match, persona name in body, reply-to-bot, no-match baseline, case-insensitive username comparison
- 3 async `save_message` DB tests: correct field values stored, `is_bot=True` + `replied_to_id`, nullable columns (`replied_to_id=None`, `sender_username=None`)
- 4 `handle_message` integration tests: unknown group silent skip (0 rows), saves incoming message with full metadata, mention detected at INFO log, no log when no mention

## Deviations from Plan

None — plan executed exactly as written. All code was taken verbatim from the plan specification. The `aiosqlite` package was already installed in the venv (pre-condition satisfied before Task 3).

## Known Stubs

None — `handle_message` saves real messages to the DB. Mention detection logs a placeholder message for Phase 4 (`"queuing reply (Phase 4)"`) but this is intentional per the plan, not a stub blocking Phase 3's goal.

## Threat Flags

None — no new network endpoints, auth paths, or file access patterns introduced beyond what the plan describes. `handle_message` reads from `update.effective_message` (PTB-provided data) and writes to the `messages` table (append-only, no user-controlled schema changes).

## Self-Check: PASSED

- bot/handlers.py exists: FOUND at /Users/ismayilismayilov/Projects/misscaddybot/bot/handlers.py
- tests/test_handlers.py exists: FOUND at /Users/ismayilismayilov/Projects/misscaddybot/tests/test_handlers.py
- main.py modified (MessageHandler registered): CONFIRMED
- Commit 5e58672 exists: FOUND
- Commit 8657b45 exists: FOUND
- Commit 7c95176 exists: FOUND
- 12 handler tests pass: CONFIRMED
- 45 total tests pass (no regressions): CONFIRMED
