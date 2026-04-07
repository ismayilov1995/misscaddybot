# tests/test_models.py
"""Tests for ORM model schema (PERS-01)."""
from sqlalchemy import inspect as sa_inspect

from bot.models import Base, Group, Message, Persona


def _col(model, name):
    """Return the Column object for a model attribute by name."""
    return model.__table__.c[name]


def test_group_columns_exist():
    cols = {c.name for c in Group.__table__.c}
    assert cols == {"id", "telegram_id", "title", "is_active", "created_at"}


def test_persona_columns_exist():
    cols = {c.name for c in Persona.__table__.c}
    assert cols == {
        "id", "group_id", "name", "bio", "personality", "language_style",
        "auto_message_enabled", "auto_message_interval_min", "auto_message_interval_max",
        "context_window", "created_at", "updated_at",
    }


def test_message_columns_exist():
    cols = {c.name for c in Message.__table__.c}
    assert cols == {
        "id", "group_id", "telegram_message_id", "sender_id", "sender_name",
        "sender_username", "text", "is_bot", "replied_to_id", "sent_at",
    }


def test_persona_group_id_is_unique():
    """group_id unique constraint enforces one-persona-per-group (PERS-01)."""
    col = _col(Persona, "group_id")
    assert col.unique is True, "Persona.group_id must be unique (one persona per group)"


def test_persona_context_window_default_is_30():
    """context_window default must be 30, not 50."""
    col = _col(Persona, "context_window")
    assert col.default.arg == 30, f"Expected default 30, got {col.default.arg}"


def test_sender_username_is_nullable():
    col = _col(Message, "sender_username")
    assert col.nullable is True, "sender_username must be nullable"


def test_replied_to_id_is_nullable():
    col = _col(Message, "replied_to_id")
    assert col.nullable is True, "replied_to_id must be nullable"


def test_group_has_one_persona_relationship():
    """Group.persona relationship uses uselist=False (one-to-one)."""
    rel = Group.__mapper__.relationships["persona"]
    assert rel.uselist is False
