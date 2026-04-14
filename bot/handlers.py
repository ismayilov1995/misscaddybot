# bot/handlers.py
import asyncio
import logging
import random
from datetime import datetime

import telegram
from telegram import Update
from telegram.constants import ChatAction, MessageEntityType
from telegram.ext import ContextTypes
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import Group, Message, Persona, MemberProfile

logger = logging.getLogger(__name__)

# Cooldown to prevent cascading follow-up chains.
# After a follow-up fires, skip follow-ups for this group for N seconds
# so the bot doesn't reply to its own follow-up endlessly.
_follow_up_cooldown: dict[int, float] = {}  # group_id -> last follow-up epoch time
_FOLLOW_UP_COOLDOWN_SECS = 300  # 5 minutes


async def get_group_with_persona(
    session: AsyncSession, telegram_id: int
) -> tuple[Group, Persona] | None:
    """
    Query Group by Telegram chat ID, eagerly loading the related Persona.

    Returns (group, persona) if found, None if the group has not been seeded.
    The caller is responsible for handling None — unregistered groups are skipped silently.
    """
    result = await session.execute(
        select(Group)
        .options(selectinload(Group.persona))
        .where(Group.telegram_id == telegram_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        return None
    return (group, group.persona)


async def save_message(
    session: AsyncSession,
    group_id: int,
    telegram_message_id: int,
    sender_id: int,
    sender_name: str,
    sender_username: str | None,
    text: str,
    is_bot: bool,
    replied_to_id: int | None,
    sent_at: datetime,
) -> Message:
    """
    Persist one Message row and return the saved ORM object.

    expire_on_commit=False is set on AsyncSessionLocal — attributes are accessible
    after commit without an extra SELECT.
    """
    message = Message(
        group_id=group_id,
        telegram_message_id=telegram_message_id,
        sender_id=sender_id,
        sender_name=sender_name,
        sender_username=sender_username,
        text=text,
        is_bot=is_bot,
        replied_to_id=replied_to_id,
        sent_at=sent_at,
    )
    session.add(message)
    await session.commit()
    return message


def is_mentioned(
    message: telegram.Message,
    bot_username: str,
    persona_name: str,
    bot_id: int,
) -> bool:
    """
    Return True if the bot is addressed in this message.

    Three detection cases (any one is sufficient):
      1. @username entity matches the bot's username (case-insensitive)
      2. Persona name appears anywhere in the message text (case-insensitive)
      3. Message is a direct reply to a message sent by the bot

    Pure function — no I/O, no DB calls, no side effects.
    """
    # Case 1: @username mention entity
    for entity in message.entities or []:
        if entity.type == MessageEntityType.MENTION:
            entity_text = message.text[entity.offset : entity.offset + entity.length]
            if entity_text.lower() == f"@{bot_username}".lower():
                return True

    # Case 2: persona name in message body
    if persona_name.lower() in (message.text or "").lower():
        return True

    # Case 3: direct reply to a bot message
    if (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
        and message.reply_to_message.from_user.id == bot_id
    ):
        return True

    return False


async def get_context_messages(
    session: AsyncSession,
    group_id: int,
    limit: int,
    after_message_id: int | None = None,
) -> list[dict]:
    """
    Fetch recent messages for a group and return them as Claude message dicts.

    If after_message_id is provided, only returns messages after that ID
    (used with rolling summaries — the summary covers everything before).

    Returns messages in chronological order (oldest first).
    is_bot=True  → {"role": "assistant", "content": text}
    is_bot=False → {"role": "user", "content": "{sender_name}: {text}"}
    """
    query = select(Message).where(Message.group_id == group_id)
    if after_message_id is not None:
        query = query.where(Message.id > after_message_id)
    result = await session.execute(
        query.order_by(Message.sent_at.desc()).limit(limit)
    )
    rows = list(reversed(result.scalars().all()))
    messages = []
    for row in rows:
        role = "assistant" if row.is_bot else "user"
        content = row.text if row.is_bot else f"{row.sender_name}: {row.text}"
        # Merge consecutive same-role messages (required by Anthropic)
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += f"\n{content}"
        else:
            messages.append({"role": role, "content": content})
    return messages


async def reply_to_mention(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group: Group,
    persona: Persona,
    reply_to_message_id: int | None = None,
    extra_memory: str = "",
) -> None:
    """
    Full reactive reply loop with human-like behaviors.

    Human features:
      • Circadian rhythm — shorter replies at night, mood hints
      • Message splitting — sometimes sends 2-3 short messages instead of one
      • Typos — occasionally makes a typo and corrects it
      • Voice — random chance to reply with voice message
    """
    from bot.database import AsyncSessionLocal
    from bot.ai import generate_reply
    from bot.humanize import (
        adjust_max_tokens, get_mood_hint,
        maybe_split_reply, maybe_add_typo,
    )

    chat_id = update.effective_message.chat_id

    async with AsyncSessionLocal() as session:
        from bot.summary import get_summary_context, maybe_generate_summary

        summary_context = await get_summary_context(session, group.id)

        context_messages = await get_context_messages(
            session, group.id, persona.context_window,
        )

        from bot.memory import get_memory_context, maybe_update_memory
        memory_context = await get_memory_context(session, group.id, context_messages)

        if extra_memory:
            memory_context = f"{memory_context}\n\n{extra_memory}" if memory_context else extra_memory

        # Circadian mood hint (time-of-day based)
        circadian_hint = get_mood_hint()
        if circadian_hint:
            memory_context = f"{memory_context}\n\n{circadian_hint}" if memory_context else circadian_hint

        # Persistent persona mood hint
        from bot.mood import get_mood_hint as get_persona_mood_hint
        persona_mood = getattr(persona, "mood", "normal") or "normal"
        persona_mood_hint = get_persona_mood_hint(persona_mood)
        if persona_mood_hint:
            memory_context = f"{memory_context}\n\n{persona_mood_hint}" if memory_context else persona_mood_hint

        # Web search for real-time questions
        msg_text = (update.effective_message.text or "")
        from bot.search import needs_search, search_web
        if needs_search(msg_text):
            search_result = await search_web(msg_text)
            if search_result:
                memory_context = f"{memory_context}\n\n{search_result}" if memory_context else search_result

        # Circadian-aware token limit
        max_tokens = adjust_max_tokens()

        # Image generation check — runs before text reply
        from bot.image_gen import should_generate_image, generate_image
        if should_generate_image(msg_text, mentioned=True):
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            img_bytes = await generate_image(msg_text, persona.name, persona.personality)
            if img_bytes:
                await asyncio.sleep(random.uniform(1, 3))
                sent_img = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=img_bytes,
                    reply_to_message_id=reply_to_message_id,
                )
                await save_message(
                    session,
                    group_id=group.id,
                    telegram_message_id=sent_img.message_id,
                    sender_id=context.bot.id,
                    sender_name=persona.name,
                    sender_username=context.bot.username,
                    text="[Şəkil göndərildi]",
                    is_bot=True,
                    replied_to_id=reply_to_message_id,
                    sent_at=sent_img.date,
                )
                logger.info("Image generated and sent in group %d", group.telegram_id)
                return  # image sent — skip text reply

        reply = await generate_reply(
            persona, context_messages,
            memory_context=memory_context,
            summary_context=summary_context,
            max_tokens=max_tokens,
        )
        if reply is None:
            return

        # Decide: voice or text?
        from bot.tts import should_send_voice, text_to_voice
        msg_text = (update.effective_message.text or "").lower()
        force_voice = any(kw in msg_text for kw in ("səslə", "sesle", "voice"))
        send_as_voice = force_voice or should_send_voice(persona.voice_chance)

        if send_as_voice:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.RECORD_VOICE
            )
            voice_buf = await text_to_voice(reply, persona_bio=persona.bio)
        else:
            voice_buf = None

        if not send_as_voice or voice_buf is None:
            # ── Text reply with human-like multi-message ──
            parts = maybe_split_reply(reply)

            sent_msg = None
            for i, part in enumerate(parts):
                # Typo chance on first or second part
                correction = None
                if i < len(parts) - 1:
                    part, correction = maybe_add_typo(part)

                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                if i == 0:
                    delay = random.uniform(1, 4) + min(len(part) * 0.04, 6)
                else:
                    delay = random.uniform(1.5, 4.0) + min(len(part) * 0.03, 4)
                await asyncio.sleep(delay)

                # Only first part replies to the original message
                reply_id = reply_to_message_id if i == 0 else None
                sent_msg = await context.bot.send_message(
                    chat_id=chat_id, text=part, reply_to_message_id=reply_id,
                )

                # Send typo correction as a quick follow-up
                if correction:
                    await asyncio.sleep(random.uniform(0.8, 2.0))
                    sent_msg = await context.bot.send_message(
                        chat_id=chat_id, text=correction,
                    )
        else:
            # Voice reply
            delay = random.uniform(1, 3)
            await asyncio.sleep(delay)

            sent_msg = await context.bot.send_voice(
                chat_id=chat_id,
                voice=voice_buf,
                reply_to_message_id=reply_to_message_id,
            )
            logger.info("Voice reply sent in group %d", group.telegram_id)

        await save_message(
            session,
            group_id=group.id,
            telegram_message_id=sent_msg.message_id,
            sender_id=context.bot.id,
            sender_name=persona.name,
            sender_username=context.bot.username,
            text=reply,
            is_bot=True,
            replied_to_id=reply_to_message_id,
            sent_at=sent_msg.date,
        )

    asyncio.create_task(maybe_update_memory(group, context_messages))
    asyncio.create_task(maybe_generate_summary(group.id, group.telegram_id))


_TEACH_KEYWORDS = ("yadda saxla", "yaddasaxla", "yaddaş:", "yaddash:", "remember:")


def _extract_teach_fact(text: str, persona_name: str, bot_username: str) -> str | None:
    """
    Extract fact from a teach command like:
      '@bot yadda saxla Kick Ruslandır'
      'Fidan yaddasaxla Mədə = Heydər'

    Returns the fact string, or None if this isn't a teach command.
    """
    lower = text.lower()

    for keyword in _TEACH_KEYWORDS:
        idx = lower.find(keyword)
        if idx == -1:
            continue
        # Extract everything after the keyword
        fact = text[idx + len(keyword):].strip()
        if fact:
            return fact

    return None


async def _handle_teach(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group: Group,
    fact: str,
) -> None:
    """Store a fact directly in GroupMemory and confirm."""
    from bot.database import AsyncSessionLocal
    from bot.memory import get_embedding
    from bot.models import GroupMemory

    async with AsyncSessionLocal() as session:
        embedding = await get_embedding(fact)

        # Skip near-duplicate if embeddings available
        if embedding is not None:
            from sqlalchemy import select as sa_select
            result = await session.execute(
                sa_select(GroupMemory.id).where(
                    GroupMemory.group_id == group.id,
                    GroupMemory.embedding.cosine_distance(embedding) < 0.08,
                ).limit(1)
            )
            if result.scalar_one_or_none() is not None:
                await context.bot.send_message(
                    chat_id=update.effective_message.chat_id,
                    text="Bunu artıq bilirəm 👍",
                    reply_to_message_id=update.effective_message.message_id,
                )
                return

        session.add(GroupMemory(
            group_id=group.id,
            fact=fact,
            embedding=embedding,
        ))
        await session.commit()

    await context.bot.send_message(
        chat_id=update.effective_message.chat_id,
        text=f"Yadda saxladım 👍",
        reply_to_message_id=update.effective_message.message_id,
    )
    logger.info("Taught fact for group %d: %s", group.telegram_id, fact[:80])


async def maybe_follow_up(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group: Group,
    persona: Persona,
) -> None:
    """
    Sometimes continue a conversation without being tagged — like a real person.

    Checks if the bot sent a message within the last 5 messages.
    If yes, 25% chance to follow up with a reply to the current message.
    """
    from bot.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        # Get last 5 messages to check if bot was recently active
        result = await session.execute(
            select(Message.is_bot, Message.telegram_message_id)
            .where(Message.group_id == group.id)
            .order_by(Message.sent_at.desc())
            .limit(5)
        )
        recent = result.all()

    if not recent:
        return

    # Was the bot active in the last 5 messages?
    bot_was_recent = any(row.is_bot for row in recent)
    if not bot_was_recent:
        return

    # Guard: skip if a follow-up was sent recently (prevents cascade chains
    # where each bot follow-up triggers another follow-up indefinitely).
    import time as _time
    now = _time.monotonic()
    if now - _follow_up_cooldown.get(group.id, 0) < _FOLLOW_UP_COOLDOWN_SECS:
        return

    # 25% chance to follow up
    if random.random() > 0.25:
        return

    _follow_up_cooldown[group.id] = now
    logger.info("Follow-up triggered in group %d", group.telegram_id)

    follow_up_hint = (
        "Sən bu söhbətdə artıq aktivsən. Kimsə bir şey yazıb — "
        "əgər mövzu sənin üçün maraqlıdırsa və ya sənə aid bir şey deyilibsə, "
        "təbii şəkildə cavab ver. Əgər mövzu sənə aid deyilsə, cavab vermə — "
        "sadəcə boş sətir qaytar."
    )

    reply = await _try_follow_up_reply(
        update, context, group, persona, follow_up_hint
    )


async def _try_follow_up_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group: Group,
    persona: Persona,
    follow_up_hint: str,
) -> None:
    """Generate a follow-up reply; skip if AI returns empty/irrelevant."""
    from bot.database import AsyncSessionLocal
    from bot.ai import generate_reply
    from bot.summary import get_summary_context

    chat_id = update.effective_message.chat_id
    trigger_message_id = update.effective_message.message_id

    async with AsyncSessionLocal() as session:
        summary_context = await get_summary_context(session, group.id)

        context_messages = await get_context_messages(
            session, group.id, persona.context_window,
        )

        from bot.memory import get_memory_context
        memory_context = await get_memory_context(session, group.id, context_messages)
        memory_context = f"{memory_context}\n\n{follow_up_hint}" if memory_context else follow_up_hint

        reply = await generate_reply(
            persona, context_messages,
            memory_context=memory_context,
            summary_context=summary_context,
        )

        # Skip if AI returned nothing useful
        if not reply or reply.strip() == "" or len(reply.strip()) < 3:
            return

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        delay = random.uniform(2, 6) + min(len(reply) * 0.04, 8)
        await asyncio.sleep(delay)

        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=reply,
            reply_to_message_id=trigger_message_id,
        )

        await save_message(
            session,
            group_id=group.id,
            telegram_message_id=sent_msg.message_id,
            sender_id=context.bot.id,
            sender_name=persona.name,
            sender_username=context.bot.username,
            text=reply,
            is_bot=True,
            replied_to_id=trigger_message_id,
            sent_at=sent_msg.date,
        )

    logger.info("Follow-up reply sent in group %d", group.telegram_id)


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    PTB MessageHandler callback — saves every group text message to the DB.

    Registered in main.py for: filters.TEXT & filters.ChatType.GROUPS

    Skips silently if:
    - update.effective_message is None (should not happen with this filter, but defensive)
    - message.text is None (photo-only, sticker, or service messages)
    - group is not in the DB (not yet seeded via seed.py)
    """
    # Import here — load_dotenv() and env validation have already run in main.py
    from bot.database import AsyncSessionLocal

    message = update.effective_message
    if message is None or message.text is None:
        return

    chat_id = message.chat_id

    async with AsyncSessionLocal() as session:
        result = await get_group_with_persona(session, chat_id)
        if result is None:
            return  # Group not seeded — skip silently
        group, persona = result

        sender_id = message.from_user.id
        sender_name = " ".join(
            filter(None, [message.from_user.first_name, message.from_user.last_name])
        )
        sender_username = message.from_user.username
        replied_to_id = (
            message.reply_to_message.message_id if message.reply_to_message else None
        )
        sent_at = message.date

        await save_message(
            session,
            group.id,
            message.message_id,
            sender_id,
            sender_name,
            sender_username,
            message.text,
            False,
            replied_to_id,
            sent_at,
        )

    # ── Track member activity (async, non-blocking) ──
    from bot.member_profiles import update_member_activity
    asyncio.create_task(
        update_member_activity(
            group.id, sender_id, sender_name, sender_username, message.text, sent_at
        )
    )

    # ── Passive emoji reaction (on ANY message, not just mentions) ──
    from bot.reactions import maybe_react
    asyncio.create_task(
        maybe_react(context.bot, chat_id, message.message_id, message.text)
    )

    # ── Link preview: fetch metadata and inject into context if links found ──
    from bot.link_preview import extract_links, should_react_to_link, fetch_link_metadata, format_link_context
    _links = extract_links(message.text)
    _link_extra_memory = ""
    if _links:
        _mentioned_now = is_mentioned(message, context.bot.username, persona.name, context.bot.id)
        if should_react_to_link(mentioned=_mentioned_now):
            try:
                _meta = await fetch_link_metadata(_links[0])
                _link_extra_memory = format_link_context(_meta)
                logger.debug("Link preview fetched for group %d: %s", chat_id, _links[0][:80])
            except Exception as _e:
                logger.debug("Link preview failed: %s", _e)

    if is_mentioned(message, context.bot.username, persona.name, context.bot.id):
        # Check for quick-teach command first
        teach_fact = _extract_teach_fact(message.text, persona.name, context.bot.username)
        if teach_fact:
            logger.info("Teach command in group %d: %s", chat_id, teach_fact[:60])
            asyncio.create_task(
                _handle_teach(update, context, group, teach_fact)
            )
        else:
            # ── Delayed reply chance: "miss" the mention, reply later ──
            from bot.humanize import should_delay_reply, get_late_prefix
            should_delay, delay_secs = should_delay_reply()

            if should_delay:
                logger.info(
                    "Delayed reply for group %d — will reply in %d seconds",
                    chat_id, delay_secs,
                )
                asyncio.create_task(
                    _delayed_mention_reply(
                        update, context, group, persona, delay_secs,
                        extra_memory=_link_extra_memory,
                    )
                )
            else:
                logger.info("Mention detected in group %d — spawning reply task", chat_id)
                asyncio.create_task(
                    reply_to_mention(update, context, group, persona, extra_memory=_link_extra_memory)
                )
    else:
        # Follow-up: if bot was active recently, sometimes continue the conversation
        asyncio.create_task(
            maybe_follow_up(update, context, group, persona)
        )


async def _delayed_mention_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group: Group,
    persona: Persona,
    delay_seconds: int,
    extra_memory: str = "",
) -> None:
    """Sleep for delay_seconds, then reply as if just saw the message."""
    from bot.humanize import get_late_prefix

    await asyncio.sleep(delay_seconds)

    late_prefix = get_late_prefix()
    logger.info("Delayed reply firing for group %d after %ds", group.telegram_id, delay_seconds)

    combined_memory = f"{late_prefix}. İndi cavab ver, amma əvvəl '{late_prefix}' de."
    if extra_memory:
        combined_memory = f"{combined_memory}\n\n{extra_memory}"

    await reply_to_mention(
        update, context, group, persona,
        reply_to_message_id=update.effective_message.message_id,
        extra_memory=combined_memory,
    )


async def handle_bot_added(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    ChatMemberHandler callback — fires when the bot's own membership status changes.

    Registered in main.py for: ChatMemberUpdated where new_chat_member is the bot
    and new status is 'member' or 'administrator'.

    Auto-seeds Group + Persona so manual seed.py is not required after deploy.
    Re-adding to an existing group is a no-op (group already in DB).
    """
    from bot.database import AsyncSessionLocal
    from seed import (
        DEFAULT_NAME, DEFAULT_BIO, DEFAULT_PERSONALITY,
        DEFAULT_LANGUAGE_STYLE, DEFAULT_AUTO_MESSAGE_ENABLED,
        DEFAULT_AUTO_MESSAGE_INTERVAL_MIN, DEFAULT_AUTO_MESSAGE_INTERVAL_MAX,
        DEFAULT_CONTEXT_WINDOW,
    )

    my_chat_member = update.my_chat_member
    if my_chat_member is None:
        return

    new_status = my_chat_member.new_chat_member.status
    if new_status not in ("member", "administrator"):
        return

    chat = my_chat_member.chat
    if chat.type not in ("group", "supergroup"):
        return

    chat_id = chat.id
    title = chat.title or "Unknown Group"

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group).where(Group.telegram_id == chat_id)
        )
        if result.scalar_one_or_none() is not None:
            logger.info("Bot re-added to known group %d — skipping seed", chat_id)
            return

        group = Group(telegram_id=chat_id, title=title, is_active=True)
        session.add(group)
        await session.flush()

        persona = Persona(
            group_id=group.id,
            name=DEFAULT_NAME,
            bio=DEFAULT_BIO,
            personality=DEFAULT_PERSONALITY,
            language_style=DEFAULT_LANGUAGE_STYLE,
            auto_message_enabled=DEFAULT_AUTO_MESSAGE_ENABLED,
            auto_message_interval_min=DEFAULT_AUTO_MESSAGE_INTERVAL_MIN,
            auto_message_interval_max=DEFAULT_AUTO_MESSAGE_INTERVAL_MAX,
            context_window=DEFAULT_CONTEXT_WINDOW,
        )
        session.add(persona)
        await session.commit()

    logger.info("Auto-seeded group '%s' (%d) with persona '%s'", title, chat_id, DEFAULT_NAME)

    # Welcome the group as the new persona
    asyncio.create_task(_send_welcome_message(context, chat_id, DEFAULT_NAME))


async def _send_welcome_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    persona_name: str,
) -> None:
    """Send a casual intro message when the bot joins a new group."""
    import random
    await asyncio.sleep(random.uniform(3, 8))
    greetings = [
        f"Salam hamıya! {persona_name} burada 👋",
        f"Hə, gəldim 😄 Salam!",
        f"Salamlar! Mən {persona_name}yəm, indi buradadır 🙂",
        f"Hə hə, mən də varım artıq 😄",
    ]
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=random.choice(greetings),
        )
    except Exception as e:
        logger.warning("Welcome message failed for chat %d: %s", chat_id, e)


async def handle_new_member(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Fires when a new member joins the group.
    Bot greets them in persona style.
    Registered for: filters.StatusUpdate.NEW_CHAT_MEMBERS
    """
    from bot.database import AsyncSessionLocal

    message = update.effective_message
    if message is None:
        return

    chat_id = message.chat_id

    async with AsyncSessionLocal() as session:
        result = await get_group_with_persona(session, chat_id)
        if result is None:
            return
        group, persona = result

    new_members = message.new_chat_members or []
    for member in new_members:
        if member.is_bot:
            continue  # don't greet other bots

        member_name = member.first_name or "Dostum"
        asyncio.create_task(
            _greet_new_member(context, chat_id, member_name, persona)
        )


async def _greet_new_member(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    member_name: str,
    persona: Persona,
) -> None:
    """Generate a persona-style greeting for the new member."""
    from bot.ai import generate_reply
    from bot.humanize import adjust_max_tokens
    import random

    await asyncio.sleep(random.uniform(2, 6))

    hint = (
        f"Qrupa '{member_name}' adlı yeni bir nəfər qoşuldu. "
        f"Onu qısa, mehriban, təbii şəkildə qarşıla — qrupun öz tərzi ilə. "
        f"Rəsmi dil yox, sanki tanış birinin dostunu qarşılayırsan. "
        f"1-2 cümlə kifayətdir."
    )

    reply = await generate_reply(
        persona,
        context_messages=[{"role": "user", "content": hint}],
        max_tokens=100,
    )

    if reply:
        try:
            await context.bot.send_message(chat_id=chat_id, text=reply)
            logger.info("Greeted new member '%s' in chat %d", member_name, chat_id)
        except Exception as e:
            logger.warning("New member greeting failed: %s", e)


async def handle_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Fires when a photo is sent to the group.
    Bot looks at the image and reacts like a real person would.
    Registered for: filters.PHOTO & filters.ChatType.GROUPS
    """
    from bot.database import AsyncSessionLocal
    from bot.vision import should_react_to_photo, describe_and_reply

    message = update.effective_message
    if message is None or not message.photo:
        return

    chat_id = message.chat_id

    async with AsyncSessionLocal() as session:
        result = await get_group_with_persona(session, chat_id)
        if result is None:
            return
        group, persona = result

        if not should_react_to_photo():
            return

        context_messages = await get_context_messages(
            session, group.id, limit=6
        )

    sender_name = "Biri"
    if message.from_user:
        sender_name = message.from_user.first_name or "Biri"

    # Get the largest photo size
    photo = message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    photo_url = tg_file.file_path

    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(photo_url)
            photo_bytes = resp.content
    except Exception as e:
        logger.warning("Could not download photo: %s", e)
        return

    caption = message.caption

    reply = await describe_and_reply(
        photo_bytes=photo_bytes,
        persona_name=persona.name,
        persona_bio=persona.bio,
        persona_personality=persona.personality,
        sender_name=sender_name,
        caption=caption,
        recent_context=context_messages,
    )

    if not reply:
        return

    await asyncio.sleep(random.uniform(2, 5))
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(random.uniform(1, 3))

    try:
        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=reply,
            reply_to_message_id=message.message_id,
        )
        async with AsyncSessionLocal() as session:
            await save_message(
                session,
                group_id=group.id,
                telegram_message_id=sent_msg.message_id,
                sender_id=context.bot.id,
                sender_name=persona.name,
                sender_username=context.bot.username,
                text=reply,
                is_bot=True,
                replied_to_id=message.message_id,
                sent_at=sent_msg.date,
            )
        logger.info("Photo reaction sent in group %d", group.telegram_id)
    except Exception as e:
        logger.warning("Photo reply send failed: %s", e)


async def handle_voice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Fires when a voice message is sent to the group.
    Transcribes with Whisper, saves as a regular message, optionally replies.
    Registered for: filters.VOICE & filters.ChatType.GROUPS
    """
    from bot.database import AsyncSessionLocal
    from bot.stt import transcribe_voice, should_react_to_voice

    message = update.effective_message
    if message is None or not message.voice:
        return

    chat_id = message.chat_id

    async with AsyncSessionLocal() as session:
        result = await get_group_with_persona(session, chat_id)
        if result is None:
            return
        group, persona = result

    sender_id = message.from_user.id if message.from_user else 0
    sender_name = "Biri"
    sender_username = None
    if message.from_user:
        sender_name = " ".join(
            filter(None, [message.from_user.first_name, message.from_user.last_name])
        ) or "Biri"
        sender_username = message.from_user.username

    # Download and transcribe
    tg_file = await context.bot.get_file(message.voice.file_id)
    voice_url = tg_file.file_path

    transcription = await transcribe_voice(voice_url)
    if not transcription:
        logger.debug("Voice transcription empty/failed in group %d", group.telegram_id)
        return

    logger.info("Voice transcribed in group %d: %s", group.telegram_id, transcription[:80])

    # Save to DB as a regular user message so it's part of conversation context
    saved_text = f"[Səs mesajı: {transcription}]"
    async with AsyncSessionLocal() as session:
        await save_message(
            session,
            group_id=group.id,
            telegram_message_id=message.message_id,
            sender_id=sender_id,
            sender_name=sender_name,
            sender_username=sender_username,
            text=saved_text,
            is_bot=False,
            replied_to_id=message.reply_to_message.message_id if message.reply_to_message else None,
            sent_at=message.date,
        )

    # Track member activity
    from bot.member_profiles import update_member_activity
    asyncio.create_task(
        update_member_activity(
            group.id, sender_id, sender_name, sender_username, saved_text, message.date
        )
    )

    # Check if bot is mentioned (by name in... well, we only have the transcription)
    mentioned = persona.name.lower() in transcription.lower()

    if not should_react_to_voice(mentioned=mentioned):
        return

    # Generate a reply that knows this was a voice message
    from bot.ai import generate_reply
    from bot.humanize import adjust_max_tokens, get_mood_hint
    from bot.summary import get_summary_context

    async with AsyncSessionLocal() as session:
        from bot.memory import get_memory_context
        summary_context = await get_summary_context(session, group.id)
        context_messages = await get_context_messages(session, group.id, persona.context_window)
        memory_context = await get_memory_context(session, group.id, context_messages)

    voice_hint = (
        f"{sender_name} bir səs mesajı göndərdi: \"{transcription}\"\n"
        f"Bunu nəzərə alaraq cavab ver — sanki real vaxtda eşitdin."
    )
    mood_hint = get_mood_hint()
    hints = "\n\n".join(filter(None, [memory_context, voice_hint, mood_hint]))

    reply = await generate_reply(
        persona, context_messages,
        memory_context=hints,
        summary_context=summary_context,
        max_tokens=adjust_max_tokens(),
    )
    if not reply:
        return

    await asyncio.sleep(random.uniform(2, 5))
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(random.uniform(1, 3))

    try:
        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=reply,
            reply_to_message_id=message.message_id,
        )
        async with AsyncSessionLocal() as session:
            await save_message(
                session,
                group_id=group.id,
                telegram_message_id=sent_msg.message_id,
                sender_id=context.bot.id,
                sender_name=persona.name,
                sender_username=context.bot.username,
                text=reply,
                is_bot=True,
                replied_to_id=message.message_id,
                sent_at=sent_msg.date,
            )
        logger.info("Voice reaction sent in group %d", group.telegram_id)
    except Exception as e:
        logger.warning("Voice reply failed: %s", e)


async def handle_audio(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Fires when a music/audio file is sent to the group.
    Saves track info to DB. 40% chance bot comments on the song.
    Registered for: filters.AUDIO & filters.ChatType.GROUPS
    """
    from bot.database import AsyncSessionLocal
    from bot.ai import generate_reply

    message = update.effective_message
    if message is None or not message.audio:
        return

    chat_id = message.chat_id

    async with AsyncSessionLocal() as session:
        result = await get_group_with_persona(session, chat_id)
        if result is None:
            return
        group, persona = result

    audio = message.audio
    title = (audio.title or "").strip() or "Naməlum"
    performer = (audio.performer or "").strip()
    track_info = f"{performer} — {title}" if performer else title
    saved_text = f"[Musiqi: {track_info}]"

    sender_id = message.from_user.id if message.from_user else 0
    sender_name = "Biri"
    sender_username = None
    if message.from_user:
        sender_name = " ".join(
            filter(None, [message.from_user.first_name, message.from_user.last_name])
        ) or "Biri"
        sender_username = message.from_user.username

    async with AsyncSessionLocal() as session:
        await save_message(
            session,
            group_id=group.id,
            telegram_message_id=message.message_id,
            sender_id=sender_id,
            sender_name=sender_name,
            sender_username=sender_username,
            text=saved_text,
            is_bot=False,
            replied_to_id=message.reply_to_message.message_id if message.reply_to_message else None,
            sent_at=message.date,
        )

    logger.info("Audio saved for group %d: %s", group.telegram_id, track_info[:60])

    # 40% chance: comment on the track
    if random.random() > 0.40:
        return

    hint = (
        f"Qrupda biri '{track_info}' musiqisini paylaşdı. "
        f"Buna münasibətini 1 cümlə ilə bil dir — qısa, təbii, öz tərzdə. "
        f"Musiqini tanıyırsansa — fikir ver, tanımırsansa — adına əsasən komment et."
    )

    reply = await generate_reply(
        persona,
        context_messages=[{"role": "user", "content": hint}],
        max_tokens=80,
    )
    if not reply:
        return

    await asyncio.sleep(random.uniform(2, 5))
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(random.uniform(1, 2))

    try:
        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=reply,
            reply_to_message_id=message.message_id,
        )
        async with AsyncSessionLocal() as session:
            await save_message(
                session,
                group_id=group.id,
                telegram_message_id=sent_msg.message_id,
                sender_id=context.bot.id,
                sender_name=persona.name,
                sender_username=context.bot.username,
                text=reply,
                is_bot=True,
                replied_to_id=message.message_id,
                sent_at=sent_msg.date,
            )
        logger.info("Audio comment sent in group %d", group.telegram_id)
    except Exception as e:
        logger.warning("Audio comment failed: %s", e)
