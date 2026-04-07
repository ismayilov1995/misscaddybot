# tests/test_ai.py
"""
Tests for bot/ai.py — system prompt builder and reply generator.

build_system_prompt is a pure function: test with real Persona instances.
generate_reply is tested only for error handling (no live API calls).
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from bot.ai import build_system_prompt, generate_reply
from bot.models import Persona


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_persona(**kwargs) -> Persona:
    """Construct a Persona instance with default test values, overridable via kwargs."""
    defaults = dict(
        group_id=1,
        name="Nicat",
        bio="26 yaşlı Bakılı oğlan.",
        personality="Rahat, mehriban.",
        language_style="Azərbaycanca + rus sözləri.",
        auto_message_enabled=True,
        auto_message_interval_min=45,
        auto_message_interval_max=180,
        context_window=30,
    )
    defaults.update(kwargs)
    return Persona(**defaults)


# ---------------------------------------------------------------------------
# build_system_prompt — pure function tests
# ---------------------------------------------------------------------------

def test_build_system_prompt_contains_name():
    persona = make_persona(name="Nicat")
    prompt = build_system_prompt(persona)
    assert "Nicat" in prompt


def test_build_system_prompt_contains_bio():
    persona = make_persona(bio="26 yaşlı Bakılı oğlan.")
    prompt = build_system_prompt(persona)
    assert "26 yaşlı Bakılı oğlan." in prompt


def test_build_system_prompt_contains_personality():
    persona = make_persona(personality="Rahat, mehriban, bəzən zarafatcıl.")
    prompt = build_system_prompt(persona)
    assert "Rahat, mehriban, bəzən zarafatcıl." in prompt


def test_build_system_prompt_contains_language_style():
    persona = make_persona(language_style="Azərbaycanca + rus sözləri.")
    prompt = build_system_prompt(persona)
    assert "Azərbaycanca + rus sözləri." in prompt


def test_build_system_prompt_contains_no_bot_rule():
    persona = make_persona()
    prompt = build_system_prompt(persona)
    assert "bot" in prompt.lower() or "AI" in prompt or "süni intellekt" in prompt
    assert "inkar" in prompt or "Heç vaxt" in prompt


def test_build_system_prompt_contains_short_reply_rule():
    persona = make_persona()
    prompt = build_system_prompt(persona)
    assert ("2" in prompt and "3" in prompt) or "qısa" in prompt.lower()


def test_build_system_prompt_returns_string():
    persona = make_persona()
    result = build_system_prompt(persona)
    assert isinstance(result, str)


def test_build_system_prompt_nonempty():
    persona = make_persona()
    result = build_system_prompt(persona)
    assert len(result) > 100, f"System prompt too short ({len(result)} chars)"


def test_build_system_prompt_different_name():
    p1 = make_persona(name="Nicat")
    p2 = make_persona(name="Anar")
    assert "Nicat" in build_system_prompt(p1)
    assert "Anar" in build_system_prompt(p2)
    assert build_system_prompt(p1) != build_system_prompt(p2)


def test_build_system_prompt_no_chatbot_framing():
    persona = make_persona()
    prompt = build_system_prompt(persona).lower()
    forbidden = ["you are an ai", "you are a chatbot", "i am an ai assistant"]
    for phrase in forbidden:
        assert phrase not in prompt, f"Forbidden phrase found: '{phrase}'"


# ---------------------------------------------------------------------------
# generate_reply — error handling tests (no live API)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_reply_returns_none_on_rate_limit():
    persona = make_persona()
    messages = [{"role": "user", "content": "Salam"}]

    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = anthropic.RateLimitError(
        message="rate limit",
        response=MagicMock(status_code=429, headers={}),
        body={},
    )

    with patch("bot.ai.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await generate_reply(persona, messages)

    assert result is None


@pytest.mark.asyncio
async def test_generate_reply_returns_none_on_connection_error():
    persona = make_persona()
    messages = [{"role": "user", "content": "Nə var?"}]

    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = anthropic.APIConnectionError(
        request=MagicMock(),
    )

    with patch("bot.ai.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await generate_reply(persona, messages)

    assert result is None


@pytest.mark.asyncio
async def test_generate_reply_returns_none_on_api_status_error():
    persona = make_persona()
    messages = [{"role": "user", "content": "Necəsən?"}]

    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = anthropic.APIStatusError(
        message="internal error",
        response=MagicMock(status_code=500, headers={}),
        body={},
    )

    with patch("bot.ai.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await generate_reply(persona, messages)

    assert result is None


@pytest.mark.asyncio
async def test_generate_reply_returns_text_on_success():
    persona = make_persona()
    messages = [{"role": "user", "content": "Salam"}]

    mock_content_block = MagicMock()
    mock_content_block.text = "Salam, necəsən?"

    mock_response = MagicMock()
    mock_response.content = [mock_content_block]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("bot.ai.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await generate_reply(persona, messages)

    assert result == "Salam, necəsən?"


@pytest.mark.asyncio
async def test_generate_reply_uses_ephemeral_cache_control():
    persona = make_persona()
    messages = [{"role": "user", "content": "Test"}]

    mock_content_block = MagicMock()
    mock_content_block.text = "ok"
    mock_response = MagicMock()
    mock_response.content = [mock_content_block]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("bot.ai.anthropic.AsyncAnthropic", return_value=mock_client):
        await generate_reply(persona, messages)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    system_arg = call_kwargs["system"]
    assert isinstance(system_arg, list), "system must be a list (not a bare string)"
    assert len(system_arg) == 1
    assert system_arg[0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_generate_reply_max_tokens_is_150():
    persona = make_persona()
    messages = [{"role": "user", "content": "Test"}]

    mock_content_block = MagicMock()
    mock_content_block.text = "ok"
    mock_response = MagicMock()
    mock_response.content = [mock_content_block]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("bot.ai.anthropic.AsyncAnthropic", return_value=mock_client):
        await generate_reply(persona, messages)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["max_tokens"] == 150
