# seed.py
"""
Seed script: create a Group and default Persona for a given Telegram group.

Usage (auto-detect from Telegram updates):
    python seed.py --auto

Usage (manual):
    python seed.py --group-id 123456789 --title "My Group"

Re-running on an existing group-id is a no-op (prints skip message, exits 0).
"""
import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

# load_dotenv() MUST come before any project imports — same rule as main.py.
# bot/database.py reads DATABASE_URL at module-import time.
load_dotenv()

if not os.getenv("DATABASE_URL"):
    sys.exit("ERROR: DATABASE_URL is not set in .env")

from sqlalchemy import select  # noqa: E402
from telegram import Bot  # noqa: E402

from bot.database import AsyncSessionLocal  # noqa: E402
from bot.models import Group, Persona  # noqa: E402

# ---------------------------------------------------------------------------
# Default persona — "Nicat"
# ---------------------------------------------------------------------------
DEFAULT_NAME = "Nicat"
DEFAULT_BIO = (
    "26 yaşlı Bakılı oğlan. IT sahəsində işləyir, futbolu sevir, "
    "dostlarla vaxt keçirməyi xoşlayır."
)
DEFAULT_PERSONALITY = (
    "Rahat, mehriban, bəzən zarafatcıl. Çox düşünmədən cavab verir. "
    "Formal deyil, amma kobud da deyil. Öz fikrini deyir."
)
DEFAULT_LANGUAGE_STYLE = (
    "Əsasən Azərbaycanca danışır, amma tez-tez rus sözləri qarışdırır "
    "(nu, davay, normalno, privet, seychas). Bəzən türk sözü işlədir. "
    "Emoji-ni çox işlətmir — nadir hallarda. Qısa cümlələr, birbaşa danışıq."
)
DEFAULT_AUTO_MESSAGE_ENABLED = True
DEFAULT_AUTO_MESSAGE_INTERVAL_MIN = 45
DEFAULT_AUTO_MESSAGE_INTERVAL_MAX = 180
DEFAULT_CONTEXT_WINDOW = 30


async def auto_detect_group() -> tuple[int, str] | None:
    """Fetch recent Telegram updates and return the first group chat found."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("ERROR: TELEGRAM_BOT_TOKEN is not set in .env")
    bot = Bot(token=token)
    updates = await bot.get_updates(limit=100)
    for update in updates:
        msg = update.message or update.edited_message
        if msg and msg.chat.type in ("group", "supergroup"):
            return msg.chat.id, msg.chat.title or "Unknown Group"
    return None


async def main(group_id: int, title: str) -> None:
    async with AsyncSessionLocal() as session:
        # Check if group already exists
        result = await session.execute(
            select(Group).where(Group.telegram_id == group_id)
        )
        existing_group = result.scalar_one_or_none()

        if existing_group is not None:
            print(f"Group {group_id} already exists, skipping.")
            return

        # Create Group
        group = Group(
            telegram_id=group_id,
            title=title,
            is_active=True,
        )
        session.add(group)
        await session.flush()  # assigns group.id without committing

        # Create Persona linked to the new Group
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

    print(
        f"Created group '{title}' (id={group_id}) with persona '{DEFAULT_NAME}'"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed a Group and Persona record")
    parser.add_argument("--auto", action="store_true", help="Auto-detect group from Telegram updates")
    parser.add_argument("--group-id", type=int, help="Telegram chat ID (bigint)")
    parser.add_argument("--title", type=str, help="Human-readable group title")
    args = parser.parse_args()

    if args.auto:
        async def run_auto():
            result = await auto_detect_group()
            if result is None:
                sys.exit("No group found. Make sure the bot is in a group and someone sent a message.")
            group_id, title = result
            print(f"Found group: '{title}' (id={group_id})")
            await main(group_id, title)
        asyncio.run(run_auto())
    else:
        if not args.group_id or not args.title:
            sys.exit("ERROR: Provide --auto, or both --group-id and --title")
        asyncio.run(main(args.group_id, args.title))
