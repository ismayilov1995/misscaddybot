---
phase: 1
plan: 1
subsystem: foundation
tags: [sqlalchemy, async, orm, database, entry-point, testing]
requires: []
provides: [bot.models, bot.database, main, test-scaffold]
affects: []
tech-stack:
  added:
    - SQLAlchemy 2.0 async ORM (AsyncAttrs + DeclarativeBase)
    - python-telegram-bot 21.10 (run_polling, post_init hook)
    - aiosqlite (in-memory SQLite for tests)
    - pytest-asyncio (asyncio_mode=auto)
  patterns:
    - load_dotenv-first import ordering
    - post_init hook for async DB init inside PTB event loop
    - expire_on_commit=False on async_sessionmaker
    - conn.run_sync() for synchronous SQLAlchemy operations in async context
key-files:
  created:
    - bot/__init__.py
    - bot/models.py
    - bot/database.py
    - main.py
    - pytest.ini
    - tests/__init__.py
    - tests/conftest.py
    - tests/test_database.py
    - tests/test_models.py
    - tests/test_startup.py
  modified: []
decisions:
  - "expire_on_commit=False is set on async_sessionmaker to prevent MissingGreenlet on attribute access after commit"
  - "main() is def not async def — run_polling() is synchronous and manages its own event loop"
  - "load_dotenv() is the first executable line in main.py, before all project imports, so DATABASE_URL is set before bot/database.py module-level engine creation"
  - "context_window default is 30 (not 50) per REQUIREMENTS.md REPLY-01"
  - "replied_to_id stores Telegram message ID (not FK) because messages can be deleted"
metrics:
  duration: ~8 minutes
  completed: 2026-04-07
  tasks_completed: 6
  files_created: 10
---

# Phase 1 Plan 1: Foundation Summary

SQLAlchemy 2.0 async ORM models, session factory with expire_on_commit=False, env-validated entry point with post_init DB hook, and pytest scaffold using in-memory SQLite — 12 tests all passing.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 0 | venv + deps | (no commit — env setup) | venv/, requirements.txt |
| 1 | bot/__init__.py | 584ae29 | bot/__init__.py |
| 2 | bot/models.py | 584ae29 | bot/models.py |
| 3 | bot/database.py | 584ae29 | bot/database.py |
| 4 | main.py | 584ae29 | main.py |
| 5 | tests | e6ff13a | pytest.ini, tests/* |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed three test correctness bugs in test_startup.py and test_database.py**

- **Found during:** Task 5 (running tests after writing)
- **Issue 1:** `test_missing_var_exits` used `cwd=str(tmp_path.parent.parent)` which resolves to a pytest temp directory, not the project root. Python could not find `main.py` → returncode 2 instead of 1.
- **Fix 1:** Replaced with `PROJECT_ROOT = str(pathlib.Path(__file__).parent.parent)` computed from the test file's location. Removed `tmp_path` fixture parameter (unused after fix).
- **Issue 2:** `test_missing_var_exits` used `env={"PATH": "/usr/bin:/bin"}` which stripped env vars but `load_dotenv()` still loaded `.env` values (e.g. `BOT_USERNAME=misscaddybot`), so validation passed and the bot tried to connect to Telegram with a placeholder token — failing with `InvalidToken` rather than the expected `ERROR:` message.
- **Fix 2:** Added all four `REQUIRED_VARS` set to empty strings in the subprocess env. `load_dotenv()` respects existing env vars (does not override) so the empty strings survive.
- **Issue 3:** `test_async_sessionmaker_expire_on_commit_false` asserted `session.expire_on_commit` but `AsyncSession` does not expose that attribute directly — it's on the underlying `session.sync_session`.
- **Fix 3:** Changed assertion to `session.sync_session.expire_on_commit is False`.
- **Issue 4:** `test_missing_telegram_token_names_var` patched `sys.exit` to raise `SystemExit(1)` but then ran the validation loop without catching the exception — the assertions after the loop were unreachable.
- **Fix 4:** Wrapped the validation loop in `try/except SystemExit: pass`.
- **Files modified:** tests/test_startup.py, tests/test_database.py
- **Commits:** e6ff13a (tests committed after fixes)

## Test Results

```
12 passed in 0.08s
```

All 12 tests pass:
- `test_database.py`: 2 tests (table creation, expire_on_commit=False)
- `test_models.py`: 8 tests (column sets, constraints, defaults, relationships)
- `test_startup.py`: 2 tests (exit on missing vars, named var in error message)

## Known Stubs

None. Phase 1 is infrastructure only — no UI or data-rendering paths exist yet.

## Threat Flags

None. Phase 1 adds no network endpoints, auth paths, or file access patterns beyond what the plan describes. The `.env` file (created from `.env.example`) contains placeholder values only and is not committed to git.

## Self-Check: PASSED

All 10 created files found on disk. Both task commits verified in git log:
- 584ae29: feat: Phase 1 foundation — models, database, main entry point
- e6ff13a: test: Phase 1 test scaffold for models, DB init, and startup validation
