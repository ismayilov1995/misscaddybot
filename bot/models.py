# bot/models.py
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    persona: Mapped["Persona"] = relationship("Persona", back_populates="group", uselist=False)
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="group")
    memories: Mapped[list["GroupMemory"]] = relationship("GroupMemory", back_populates="group")
    summaries: Mapped[list["GroupSummary"]] = relationship("GroupSummary", back_populates="group")
    member_profiles: Mapped[list["MemberProfile"]] = relationship("MemberProfile", back_populates="group")


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    bio: Mapped[str] = mapped_column(Text, nullable=False)
    personality: Mapped[str] = mapped_column(Text, nullable=False)
    language_style: Mapped[str] = mapped_column(Text, nullable=False)
    auto_message_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_message_interval_min: Mapped[int] = mapped_column(Integer, default=45, nullable=False)
    auto_message_interval_max: Mapped[int] = mapped_column(Integer, default=180, nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    voice_chance: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="az", nullable=False)
    mood: Mapped[str] = mapped_column(String(20), default="normal", nullable=False, server_default="normal")
    memory: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    group: Mapped["Group"] = relationship("Group", back_populates="persona")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    replied_to_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped["Group"] = relationship("Group", back_populates="messages")


class GroupSummary(Base):
    __tablename__ = "group_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    last_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # level=1: summary of raw messages (short-term)
    # level=2: meta-summary of 4 L1 summaries (medium-term memory)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    group: Mapped["Group"] = relationship("Group", back_populates="summaries")


class GroupMemory(Base):
    __tablename__ = "group_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False, index=True)
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    group: Mapped["Group"] = relationship("Group", back_populates="memories")


class MemberProfile(Base):
    """Per-member profile — interests, activity patterns, last seen."""
    __tablename__ = "member_profiles"
    __table_args__ = (UniqueConstraint("group_id", "sender_id", name="uq_member_group"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False, index=True)
    sender_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # AI-generated observations about this member
    profile_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Comma-separated list of active hours e.g. "20,21,22,23"
    active_hours: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Birthday stored as "MM-DD" string
    birthday: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    group: Mapped["Group"] = relationship("Group", back_populates="member_profiles")
