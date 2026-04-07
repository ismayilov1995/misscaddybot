---
phase: 4
plan: 1
subsystem: handlers
tags: [telegram, ptb, reactive-reply, typing-simulation, claude-api, async]
dependency_graph:
  requires: [bot/handlers.py (existing), bot/ai.py, bot/database.py, bot/models.py]
  provides: [get_context_messages, reply_to_mention, updated handle_message]
  affects: []
tech_stack:
  added: []
  patterns: [asyncio.create_task, in-function import, desc+reverse for chronological fetch]
key_files:
  modified: [bot/handlers.py, tests/test_handlers.py]
decisions:
  - get_context_messages uses ORDER BY sent_at DESC + LIMIT then reverses list — single query, correct chronological output
  - reply_to_mention imports AsyncSessionLocal and generate_reply inside function body — matches existing handle_message pattern, avoids circular import risk
  - asyncio.create_task used in handle_message so the session context is already closed before reply_to_mention opens its own — no session sharing between tasks
  - delay formula: random.uniform(1, 4) + min(len(reply) * 0.04, 8) — base 1–4s + length cap at 8s, total ceiling ~12s
metrics:
  duration: 180s
  completed: 2026-04-07
  tasks_completed: 1
  files_modified: 2
---

# Phase 4 Plan 1: Reactive Reply Loop Summary

When mentioned, the bot now fetches recent conversation history, calls Claude, shows a typing indicator, waits a realistic delay, sends the reply, and saves the outgoing message to DB.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Implement get_context_messages + reply_to_mention; update handle_message stub | d9a27b0 |

## What Was Built

**bot/handlers.py** (new functions + updated stub)

- `get_context_messages(session, group_id, limit)` — queries Message table DESC by sent_at, reverses for chronological order, formats rows as Claude message dicts (`role="assistant"` for bot, `role="user"` with `"{sender_name}: {text}"` for humans)
- `reply_to_mention(update, context, group, persona)` — full reply coroutine: fetches context, calls `generate_reply()`, returns silently on None, sends `ChatAction.TYPING`, sleeps `random.uniform(1,4) + min(len(reply)*0.04, 8)` seconds, sends message, saves outgoing message to DB with `is_bot=True`
- `handle_message()` — stub replaced: `asyncio.create_task(reply_to_mention(update, context, group, persona))`

**tests/test_handlers.py** — 8 new tests (20 total in file, 53 total suite)

- 5 `get_context_messages` tests: empty DB, chronological order, user role format, assistant role format, limit enforcement (returns N most recent)
- 3 `reply_to_mention` tests: None reply → no send_message called; reply sent and saved to DB; typing action + sleep >= 1.0s

## Deviations from Plan

None — implemented exactly as specified.

## Known Stubs

None — `handle_message` now fires a real reply task. Phase 4 goal is fully delivered.

## Self-Check: PASSED

- bot/handlers.py exports get_context_messages, reply_to_mention: CONFIRMED
- handle_message calls asyncio.create_task(reply_to_mention(...)): CONFIRMED
- 53 tests pass, 0 failures: CONFIRMED
- Import check: python -c "from bot.handlers import get_context_messages, reply_to_mention, handle_message; print('OK')": OK
