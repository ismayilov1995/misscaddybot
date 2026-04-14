# bot/scheduler.py
import asyncio
import logging
import random

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.models import Group, Persona

logger = logging.getLogger(__name__)


async def send_auto_message(application) -> None:
    """
    APScheduler job — sends a spontaneous message to every active group
    where auto_message_enabled=True.

    Fetches recent context, calls Claude, sends reply, saves to DB.
    Errors are caught per-group so one failure does not block others.
    """
    from bot.database import AsyncSessionLocal
    from bot.ai import generate_reply
    from bot.handlers import get_context_messages, save_message

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .where(Group.is_active == True)  # noqa: E712
        )
        groups = result.scalars().all()

    for group in groups:
        persona = group.persona
        if persona is None or not persona.auto_message_enabled:
            continue

        try:
            # ── 10% chance: send a poll instead of a text message ──
            if random.random() < 0.10:
                poll_sent = await _try_send_poll(application, group, persona)
                if poll_sent:
                    continue  # skip text auto-message for this iteration

            async with AsyncSessionLocal() as session:
                from bot.summary import get_summary_context, maybe_generate_summary

                summary_context = await get_summary_context(session, group.id)

                context_messages = await get_context_messages(
                    session, group.id, persona.context_window,
                )

            # 20% chance: conversation starter — longer, topic-opening message
            is_conversation_starter = random.random() < 0.20
            if is_conversation_starter:
                starter_hint = (
                    "İndi söhbətə yeni mövzu aç. Maraqlı bir şey paylaş, sual soruş, "
                    "fikir bildir — qrupdakıların cavab vermək istəyəcəyi bir şey olsun. "
                    "Qrupun maraqlarına və əvvəlki söhbətlərə uyğun mövzu seç. "
                    "Təbii yaz, sanki ağlına gəldi."
                )
                reply = await generate_reply(
                    persona, context_messages,
                    memory_context=starter_hint,
                    summary_context=summary_context,
                    max_tokens=500,
                )
                logger.info("Conversation starter sent to group %d", group.telegram_id)
            else:
                reply = await generate_reply(persona, context_messages, summary_context=summary_context)

            if reply is None:
                logger.warning("Auto-message skipped for group %d — Claude returned None", group.telegram_id)
                continue

            sent_msg = await application.bot.send_message(
                chat_id=group.telegram_id, text=reply
            )

            async with AsyncSessionLocal() as session:
                await save_message(
                    session,
                    group_id=group.id,
                    telegram_message_id=sent_msg.message_id,
                    sender_id=application.bot.id,
                    sender_name=persona.name,
                    sender_username=application.bot.username,
                    text=reply,
                    is_bot=True,
                    replied_to_id=None,
                    sent_at=sent_msg.date,
                )

            logger.info("Auto-message sent to group %d", group.telegram_id)
            asyncio.create_task(maybe_generate_summary(group.id, group.telegram_id))

        except Exception as e:
            logger.warning("Auto-message failed for group %d: %s", group.telegram_id, e)


async def _try_send_poll(application, group, persona) -> bool:
    """
    Generate and send a fun poll to the group.
    Returns True if a poll was sent, False on failure.
    """
    import json
    import anthropic
    import os

    poll_prompt = (
        f"Sən '{persona.name}' adlı birisisən. Bu Telegram qrupu üçün maraqlı bir sorğu-anket hazırla. "
        "Yalnız JSON formatında cavab ver, başqa heç nə yazma:\n"
        '{"question": "...", "options": ["seçim1", "seçim2", "seçim3", "seçim4"]}\n'
        "Mövzu: gündəlik həyat, rəy, tercih, əyləncəli sual. Azərbaycan dilində."
    )

    try:
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=200,
            messages=[{"role": "user", "content": poll_prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        poll_data = json.loads(raw)
        question = poll_data.get("question", "").strip()
        options = [str(o).strip() for o in poll_data.get("options", []) if str(o).strip()]

        if not question or len(options) < 2:
            return False

        await application.bot.send_poll(
            chat_id=group.telegram_id,
            question=question[:300],
            options=[o[:100] for o in options[:10]],
            is_anonymous=False,
        )
        logger.info("Auto poll sent to group %d: %s", group.telegram_id, question[:60])
        return True

    except Exception as e:
        logger.debug("Poll generation failed for group %d: %s", group.telegram_id, e)
        return False


async def shift_group_moods(application) -> None:
    """
    APScheduler job — runs every 3 hours.
    Each persona has a 20% chance to transition to an adjacent mood.
    """
    from bot.database import AsyncSessionLocal
    from bot.mood import shift_mood

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .where(Group.is_active == True)  # noqa: E712
        )
        groups = result.scalars().all()

    for group in groups:
        persona = group.persona
        if persona is None:
            continue

        current_mood = getattr(persona, "mood", "normal") or "normal"
        new_mood = shift_mood(current_mood)

        if new_mood != current_mood:
            try:
                async with AsyncSessionLocal() as session:
                    from sqlalchemy import select as sa_select
                    result = await session.execute(
                        sa_select(Persona).where(Persona.group_id == group.id)
                    )
                    p = result.scalar_one_or_none()
                    if p:
                        p.mood = new_mood
                        await session.commit()
                logger.info(
                    "Mood shift for group %d: %s → %s",
                    group.telegram_id, current_mood, new_mood,
                )
            except Exception as e:
                logger.warning("Mood shift failed for group %d: %s", group.telegram_id, e)


async def update_group_memory(application) -> None:
    """
    APScheduler job — runs every 24 hours.

    For each active group, fetches the last 100 messages, sends them to Claude
    and asks it to write short observations about the group (inside jokes,
    recurring topics, who's who, group vibe). Saves the result to persona.memory.

    This memory is then injected into the system prompt on every reply,
    allowing the bot's character to evolve and adapt to the group over time.
    """
    from bot.database import AsyncSessionLocal
    from bot.handlers import get_context_messages

    async with AsyncSessionLocal() as session:
        from sqlalchemy.orm import selectinload
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .where(Group.is_active == True)  # noqa: E712
        )
        groups = result.scalars().all()

    for group in groups:
        persona = group.persona
        if persona is None:
            continue

        try:
            async with AsyncSessionLocal() as session:
                messages = await get_context_messages(session, group.id, limit=100)

            if len(messages) < 10:
                logger.info("Group %d has < 10 messages — skipping memory update", group.telegram_id)
                continue

            # Format messages as plain text for the reflection prompt
            convo = "\n".join(
                f"{'Bot' if m['role'] == 'assistant' else 'İnsan'}: {m['content']}"
                for m in messages
            )

            reflection_prompt = (
                "Aşağıda bir Telegram qrupunun söhbət tarixçəsi var. "
                "Sən bu qrupun üzvüsən və bu söhbəti oxuyursan.\n\n"
                f"{convo}\n\n"
                "Bu söhbətə əsaslanaraq qrup haqqında 3-5 cümlə ilə qeyd yaz: "
                "kim kimdir, nə mövzular çıxır, hansı inside joke-lar var, qrupun ümumi havası necədir. "
                "Şəxsi qeyd kimi yaz, sanki öz notlarındır."
            )

            import anthropic
            import os
            client = anthropic.AsyncAnthropic()
            response = await client.messages.create(
                model=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
                max_tokens=300,
                messages=[{"role": "user", "content": reflection_prompt}],
            )
            new_memory = response.content[0].text.strip()

            async with AsyncSessionLocal() as session:
                from sqlalchemy import select as sa_select
                result = await session.execute(
                    sa_select(Persona).where(Persona.group_id == group.id)
                )
                p = result.scalar_one_or_none()
                if p:
                    p.memory = new_memory
                    await session.commit()

            logger.info("Memory updated for group %d", group.telegram_id)

        except Exception as e:
            logger.warning("Memory update failed for group %d: %s", group.telegram_id, e)


async def send_weekly_digest(application) -> None:
    """
    APScheduler job — runs every Sunday at 10:00 AM Baku time.
    Sends a fun weekly recap to every active group.
    """
    from bot.database import AsyncSessionLocal
    from bot.weekly_digest import generate_weekly_digest

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .where(Group.is_active == True)  # noqa: E712
        )
        groups = result.scalars().all()

    for group in groups:
        persona = group.persona
        if persona is None or not persona.auto_message_enabled:
            continue
        try:
            digest = await generate_weekly_digest(group.id, group.telegram_id, persona)
            if digest:
                await application.bot.send_message(
                    chat_id=group.telegram_id, text=digest
                )
                logger.info("Weekly digest sent to group %d", group.telegram_id)
        except Exception as e:
            logger.warning("Weekly digest failed for group %d: %s", group.telegram_id, e)


async def check_birthdays(application) -> None:
    """
    APScheduler job — runs daily at 09:00 AM Baku time.
    Sends birthday greetings for members whose birthday is today.
    """
    from bot.database import AsyncSessionLocal
    from bot.member_profiles import get_todays_birthdays
    from bot.ai import generate_reply

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .where(Group.is_active == True)  # noqa: E712
        )
        groups = result.scalars().all()

    for group in groups:
        persona = group.persona
        if persona is None:
            continue
        try:
            async with AsyncSessionLocal() as session:
                birthday_members = await get_todays_birthdays(session, group.id)

            for member in birthday_members:
                hint = (
                    f"Bu gün {member.sender_name}-in ad günüdür! "
                    f"Onu təbrik et — qısa, səmimi, qrupun öz tərzi ilə. "
                    f"Rəsmi yox, real dost kimi."
                )
                reply = await generate_reply(
                    persona,
                    context_messages=[{"role": "user", "content": hint}],
                    max_tokens=120,
                )
                if reply:
                    await application.bot.send_message(
                        chat_id=group.telegram_id, text=reply
                    )
                    logger.info(
                        "Birthday greeting sent for %s in group %d",
                        member.sender_name, group.telegram_id,
                    )
        except Exception as e:
            logger.warning("Birthday check failed for group %d: %s", group.telegram_id, e)


async def check_silent_members(application) -> None:
    """
    APScheduler job — runs every 12 hours.
    If a regular member has been silent for 48+ hours, bot may mention them.
    """
    from bot.database import AsyncSessionLocal
    from bot.member_profiles import get_silent_members
    from bot.ai import generate_reply

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .where(Group.is_active == True)  # noqa: E712
        )
        groups = result.scalars().all()

    for group in groups:
        persona = group.persona
        if persona is None or not persona.auto_message_enabled:
            continue
        try:
            async with AsyncSessionLocal() as session:
                silent = await get_silent_members(session, group.id, hours_threshold=48)

            if not silent:
                continue

            # Pick one silent member to mention (don't spam)
            member = random.choice(silent)
            hint = (
                f"{member.sender_name} bir neçə gündür yazılmayıb. "
                f"Onu qısa, təbii şəkildə xatırla — zarafatla, narahat olmadan. "
                f"Sanki dostun haqqında düşündün."
            )
            reply = await generate_reply(
                persona,
                context_messages=[{"role": "user", "content": hint}],
                max_tokens=100,
            )
            if reply:
                await application.bot.send_message(
                    chat_id=group.telegram_id, text=reply
                )
                logger.info(
                    "Silent member mention: %s in group %d",
                    member.sender_name, group.telegram_id,
                )
        except Exception as e:
            logger.warning("Silent member check failed for group %d: %s", group.telegram_id, e)


def build_scheduler(application) -> AsyncIOScheduler:
    """
    Create and configure the AsyncIOScheduler.
    """
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        send_auto_message,
        trigger="interval",
        minutes=45,
        jitter=135 * 60,
        args=[application],
        id="auto_message",
        name="Auto message job",
        replace_existing=True,
    )

    scheduler.add_job(
        update_group_memory,
        trigger="interval",
        hours=24,
        args=[application],
        id="update_memory",
        name="Group memory update",
        replace_existing=True,
    )

    # Weekly digest — every Sunday at 10:00 AM Baku time (UTC+4 = 06:00 UTC)
    scheduler.add_job(
        send_weekly_digest,
        trigger="cron",
        day_of_week="sun",
        hour=6,
        minute=0,
        args=[application],
        id="weekly_digest",
        name="Weekly group digest",
        replace_existing=True,
    )

    # Birthday greetings — every day at 09:00 AM Baku time (05:00 UTC)
    scheduler.add_job(
        check_birthdays,
        trigger="cron",
        hour=5,
        minute=0,
        args=[application],
        id="birthday_check",
        name="Birthday check",
        replace_existing=True,
    )

    # Silent member check — every 12 hours
    scheduler.add_job(
        check_silent_members,
        trigger="interval",
        hours=12,
        jitter=1800,
        args=[application],
        id="silent_members",
        name="Silent member check",
        replace_existing=True,
    )

    # Mood shifts — every 3 hours, each persona has 20% chance to change mood
    scheduler.add_job(
        shift_group_moods,
        trigger="interval",
        hours=3,
        jitter=600,
        args=[application],
        id="mood_shift",
        name="Persona mood shift",
        replace_existing=True,
    )

    return scheduler
