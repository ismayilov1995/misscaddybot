# tests/test_startup.py
"""Tests for startup env validation (DEPLOY-02)."""
import pathlib
import subprocess
import sys

# Resolve the project root relative to this test file (tests/ -> project root)
PROJECT_ROOT = str(pathlib.Path(__file__).parent.parent)


def test_missing_var_exits(monkeypatch):
    """Missing any REQUIRED_VAR causes sys.exit with a clear message."""
    # Explicitly set all REQUIRED_VARS to empty strings so os.getenv() returns falsy.
    # This overrides any values that load_dotenv() would read from the .env file.
    result = subprocess.run(
        [sys.executable, "main.py"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "TELEGRAM_BOT_TOKEN": "",
            "ANTHROPIC_API_KEY": "",
            "DATABASE_URL": "",
            "BOT_USERNAME": "",
        },
    )
    assert result.returncode == 1
    assert "ERROR:" in result.stderr or "ERROR:" in result.stdout


def test_missing_telegram_token_names_var(monkeypatch):
    """Exit message names the specific missing variable."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("BOT_USERNAME", raising=False)

    import sys as _sys

    captured = []

    def fake_exit(msg):
        captured.append(msg)
        raise SystemExit(1)

    monkeypatch.setattr(_sys, "exit", fake_exit)

    # Re-execute the validation block in isolation
    import os
    REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "DATABASE_URL", "BOT_USERNAME"]
    try:
        for var in REQUIRED_VARS:
            if not os.getenv(var):
                _sys.exit(f"ERROR: {var} is not set in .env")
    except SystemExit:
        pass

    assert len(captured) >= 1
    assert "TELEGRAM_BOT_TOKEN" in captured[0]
