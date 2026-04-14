# main.py
import logging
import os
import sys

from dotenv import load_dotenv

# load_dotenv() MUST come before any project imports.
# bot/database.py reads os.environ["DATABASE_URL"] at module level.
# If this line comes after the import, DATABASE_URL won't be set yet → KeyError.
load_dotenv()

# Validate all required vars before any initialization.
# Explicit naming makes misconfigured deployments easy to diagnose.
REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "DATABASE_URL", "BOT_USERNAME"]
for var in REQUIRED_VARS:
    if not os.getenv(var):
        sys.exit(f"ERROR: {var} is not set in .env")

# Project imports come AFTER load_dotenv() and env validation.
from telegram.ext import Application, ChatMemberHandler, InlineQueryHandler, MessageHandler, filters  # noqa: E402

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


async def post_init(application: Application) -> None:
    """
    Runs inside PTB's event loop after initialize(), before start_polling().
    This is the correct place for async startup work (DB init, scheduler start).
    """
    from bot.database import init_db
    from bot.scheduler import build_scheduler
    await init_db()
    logger.info("Database initialized — all tables ready")
    scheduler = build_scheduler(application)
    scheduler.start()
    logger.info("Scheduler started — auto-messages active")


def main() -> None:
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    from bot.handlers import handle_message, handle_bot_added, handle_photo, handle_new_member, handle_voice, handle_audio
    from bot.inline import handle_inline_query
    app.add_handler(ChatMemberHandler(handle_bot_added, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.GROUPS, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE & filters.ChatType.GROUPS, handle_voice))
    app.add_handler(MessageHandler(filters.AUDIO & filters.ChatType.GROUPS, handle_audio))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_member))
    app.add_handler(InlineQueryHandler(handle_inline_query))

    logger.info("Starting bot...")
    app.run_polling(allowed_updates=["message", "my_chat_member", "chat_member", "inline_query"])


if __name__ == "__main__":
    main()
