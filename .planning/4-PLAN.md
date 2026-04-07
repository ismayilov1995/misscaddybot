---
phase: 4
plan: 1
type: tdd
wave: 1
depends_on: []
files_modified:
  - bot/handlers.py
  - tests/test_handlers.py
autonomous: true
requirements:
  - REPLY-01
  - REPLY-02
  - REPLY-03
  - REPLY-04
  - REPLY-05
  - AI-01
  - AI-02
  - AI-03

must_haves:
  truths:
    - "When mentioned, the bot sends a typing action before replying"
    - "The bot waits at least 1 second (base delay) before sending any reply"
    - "Longer replies take longer to appear — delay scales with character count"
    - "The bot's outgoing reply is saved to the messages table with is_bot=True"
    - "When the Claude API returns None (error), no message is sent and no crash occurs"
    - "Context sent to Claude is the last N messages in chronological order, formatted as Claude roles"
  artifacts:
    - path: "bot/handlers.py"
      provides: "get_context_messages, reply_to_mention, updated handle_message"
      exports:
        - get_context_messages
        - reply_to_mention
    - path: "tests/test_handlers.py"
      provides: "Tests for all new functions"
  key_links:
    - from: "bot/handlers.py handle_message()"
      to: "reply_to_mention()"
      via: "asyncio.create_task()"
      pattern: "create_task.*reply_to_mention"
    - from: "reply_to_mention()"
      to: "bot/ai.py generate_reply()"
      via: "direct async call"
      pattern: "await generate_reply"
    - from: "reply_to_mention()"
      to: "messages table"
      via: "save_message() with is_bot=True"
      pattern: "save_message.*is_bot=True"
---

<objective>
Implement the full reactive reply loop in bot/handlers.py.

When handle_message detects a mention, it spawns reply_to_mention as a background task. That coroutine fetches recent conversation history, calls the Claude API, simulates human typing delay, sends the reply, and saves the bot's outgoing message to the DB.

Purpose: Closes the mention-detection stub left by Phase 3 and delivers the core value of the bot — a persona-driven reply that feels like a real person in the chat.
Output: Two new functions in bot/handlers.py (get_context_messages, reply_to_mention), updated handle_message, and tests covering all observable behaviors.
</objective>

<execution_context>
@/Users/ismayilismayilov/Projects/misscaddybot/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ismayilismayilov/Projects/misscaddybot/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md

# Phase history — directly depended upon
@.planning/3-1-SUMMARY.md
@.planning/2-1-SUMMARY.md

# Source files being modified
@bot/handlers.py
@bot/ai.py
@bot/models.py
@bot/database.py

# Existing test file being extended
@tests/test_handlers.py
@tests/conftest.py
</context>

<interfaces>
<!-- Key contracts the executor needs. No codebase exploration required. -->

From bot/handlers.py (existing — do not modify these signatures):
```python
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
) -> Message: ...

async def get_group_with_persona(
    session: AsyncSession, telegram_id: int
) -> tuple[Group, Persona] | None: ...
```

From bot/ai.py (existing — call as-is):
```python
async def generate_reply(
    persona: Persona,
    context_messages: list[dict],  # [{"role": "user"|"assistant", "content": str}]
) -> str | None: ...  # None = API error, caller must handle
```

From bot/models.py (existing ORM):
```python
class Message:
    id: int
    group_id: int
    telegram_message_id: int
    sender_id: int
    sender_name: str
    sender_username: str | None
    text: str
    is_bot: bool
    replied_to_id: int | None
    sent_at: datetime

class Persona:
    context_window: int   # default=30, controls how many messages to fetch
    name: str

class Group:
    id: int
    telegram_id: int
```

From telegram-bot library (PTB):
```python
# ChatAction enum used for typing indicator
from telegram.constants import ChatAction
# ChatAction.TYPING is the correct value

# Sending actions:
await context.bot.send_chat_action(chat_id=int, action=ChatAction.TYPING)
sent_msg = await context.bot.send_message(chat_id=int, text=str)
# sent_msg.message_id → int
# sent_msg.date → datetime (timezone-aware)
# context.bot.id → int
# context.bot.username → str
```
</interfaces>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Implement get_context_messages and reply_to_mention; update handle_message</name>
  <files>bot/handlers.py, tests/test_handlers.py</files>
  <behavior>
    get_context_messages behavior:
    - With 0 messages in DB → returns []
    - With 5 messages of mixed is_bot values → returns all 5 in chronological order (oldest first), regardless of sent_at ordering stored in DB
    - is_bot=False message → dict with role="user", content="{sender_name}: {text}"
    - is_bot=True message → dict with role="assistant", content="{text}" (no name prefix)
    - With limit=3 and 10 messages in DB → returns the 3 most recent messages, in chronological order

    reply_to_mention behavior:
    - generate_reply returns None → context.bot.send_message is NOT called; no exception raised
    - generate_reply returns "Salam!" → context.bot.send_message called once with that text
    - After send_message → save_message called with is_bot=True and the sent message's telegram_message_id
    - asyncio.sleep is called with a value >= 1.0 (base delay floor)
    - asyncio.sleep is called with a value <= 13.0 (1 base + 4 max base + 8 char cap — practical upper bound)
    - send_chat_action called with ChatAction.TYPING before send_message

    handle_message behavior:
    - When mention detected → asyncio.create_task is called (reply task spawned)
    - When no mention → asyncio.create_task is NOT called
  </behavior>
  <action>
Write tests first (RED), then implement (GREEN).

--- IMPORTS TO ADD at top of bot/handlers.py ---

Add these imports (alongside existing imports):
  import asyncio
  import random
  from telegram.constants import ChatAction   # MessageEntityType already imported

--- NEW FUNCTION 1: get_context_messages ---

Signature:
  async def get_context_messages(
      session: AsyncSession,
      group_id: int,
      limit: int,
  ) -> list[dict]:

Implementation:
  result = await session.execute(
      select(Message)
      .where(Message.group_id == group_id)
      .order_by(Message.sent_at.desc())
      .limit(limit)
  )
  rows = result.scalars().all()
  # rows are newest-first from the DESC query; reverse to get chronological order
  rows = list(reversed(rows))
  messages = []
  for row in rows:
      if row.is_bot:
          messages.append({"role": "assistant", "content": row.text})
      else:
          messages.append({"role": "user", "content": f"{row.sender_name}: {row.text}"})
  return messages

--- NEW FUNCTION 2: reply_to_mention ---

Signature:
  async def reply_to_mention(
      update: Update,
      context: ContextTypes.DEFAULT_TYPE,
      group,       # Group ORM object
      persona,     # Persona ORM object
  ) -> None:

Implementation:
  from bot.database import AsyncSessionLocal
  from bot.ai import generate_reply

  chat_id = update.effective_message.chat_id

  async with AsyncSessionLocal() as session:
      context_messages = await get_context_messages(
          session, group.id, persona.context_window
      )
      reply = await generate_reply(persona, context_messages)
      if reply is None:
          return

      await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
      delay = random.uniform(1, 4) + min(len(reply) * 0.04, 8)
      await asyncio.sleep(delay)

      sent_msg = await context.bot.send_message(chat_id=chat_id, text=reply)

      await save_message(
          session,
          group_id=group.id,
          telegram_message_id=sent_msg.message_id,
          sender_id=context.bot.id,
          sender_name=persona.name,
          sender_username=context.bot.username,
          text=reply,
          is_bot=True,
          replied_to_id=None,
          sent_at=sent_msg.date,
      )

NOTE: Both imports (AsyncSessionLocal and generate_reply) go inside the function body —
same pattern as handle_message's existing "from bot.database import AsyncSessionLocal".
This avoids circular import risk and matches the established project convention.

--- UPDATE handle_message() ---

Replace the current stub in handle_message (the logger.info("queuing reply (Phase 4)") line):

  if is_mentioned(message, context.bot.username, persona.name, context.bot.id):
      logger.info("Mention detected in group %d — spawning reply task", chat_id)
      asyncio.create_task(reply_to_mention(update, context, group, persona))

The session is already closed at this point (the async with block above has exited) —
group and persona are detached ORM objects but their attributes are accessible because
expire_on_commit=False is set on AsyncSessionLocal. This is safe.

--- TESTS to add to tests/test_handlers.py ---

Update the import line at the top to add the new functions:
  from bot.handlers import (
      get_group_with_persona, is_mentioned, save_message,
      handle_message, get_context_messages, reply_to_mention,
  )

Add 8 new test functions in a new section "# get_context_messages" and "# reply_to_mention":

1. test_get_context_messages_empty — 0 rows → []
2. test_get_context_messages_chronological_order — insert 3 rows with distinct sent_at
   timestamps, assert result[0].sent_at < result[1].sent_at (check content order, not
   ORM objects — check the "content" values match expected chronological sequence)
3. test_get_context_messages_user_role_format — is_bot=False row → role="user",
   content starts with sender_name + ": "
4. test_get_context_messages_assistant_role_format — is_bot=True row → role="assistant",
   content equals the text field with no name prefix
5. test_get_context_messages_limit — insert 5 rows, call with limit=3, assert len==3
   and the 3 most recent rows are returned (not the 3 oldest)
6. test_reply_to_mention_none_reply_no_send — patch generate_reply to return None,
   assert context.bot.send_message not called
7. test_reply_to_mention_sends_and_saves — patch generate_reply to return "Salam!",
   assert send_message called with text="Salam!", assert a Message row with is_bot=True
   and text="Salam!" exists in DB after the call
8. test_reply_to_mention_typing_delay — patch generate_reply to return "ok", patch
   asyncio.sleep as AsyncMock, assert asyncio.sleep was called with a value >= 1.0
   and send_chat_action was called with action=ChatAction.TYPING

For tests 6-8, construct reply_to_mention arguments as follows:
  - update: use _make_update() helper already in the file
  - context: use _make_context() helper, but add AsyncMock for send_chat_action
    and send_message on context.bot
  - group, persona: use make_group_with_persona fixture

For test 7, mock sent_msg returned by send_message:
  sent_msg = MagicMock()
  sent_msg.message_id = 999
  sent_msg.date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
  context.bot.send_message = AsyncMock(return_value=sent_msg)

For test 7's DB assertion — after awaiting reply_to_mention, query the DB for
Message rows where is_bot=True to confirm the outgoing message was persisted.
  </action>
  <verify>
    <automated>cd /Users/ismayilismayilov/Projects/misscaddybot && python -m pytest tests/test_handlers.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>
    - All existing 12 handler tests still pass (no regressions)
    - 8 new tests pass
    - Total test_handlers.py tests: 20
    - get_context_messages, reply_to_mention exported from bot/handlers.py
    - handle_message calls asyncio.create_task(reply_to_mention(...)) on mention
    - Full test suite passes: python -m pytest -x -q shows no failures
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>
    Full reactive reply loop in bot/handlers.py. When the bot is mentioned in a
    registered group it: fetches last N messages from DB, calls Claude, shows typing
    indicator, waits realistic delay, sends reply, saves outgoing message to DB.
  </what-built>
  <how-to-verify>
    1. Ensure .env has TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, DATABASE_URL, BOT_USERNAME set
    2. Run: python seed.py --group-id YOUR_GROUP_ID --title "Test Group" (if not already seeded)
    3. Start bot: python main.py
    4. In the Telegram group: send a message mentioning the bot by @username or persona name
    5. Confirm you see the typing indicator in the chat before the reply appears
    6. Confirm the reply arrives after a short delay (1–4+ seconds)
    7. Confirm the reply sounds in-character (short, casual, Azerbaijani voice)
    8. Send a message WITHOUT mentioning the bot — confirm no reply is sent
    9. Optional: Check the messages table — the bot's outgoing message should appear with is_bot=true
  </how-to-verify>
  <resume-signal>Type "approved" if the bot replies correctly, or describe any issues observed</resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Telegram → bot | All message content arrives via PTB update objects; user controls text, sender name, and entity positions |
| bot → Anthropic API | System prompt and context messages are sent as structured JSON; text from DB is interpolated into content fields |
| Anthropic API → bot | Reply text is returned and sent verbatim to the Telegram group |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-4-01 | Tampering | context message formatting in get_context_messages | accept | Sender name and text come from the messages table which was written by save_message — data is already stored, not re-validated at read time. Injection into Claude's context is low-risk: Claude is instructed to reply in persona voice, not execute instructions |
| T-4-02 | Denial of Service | reply_to_mention asyncio.sleep + API call | accept | Calls are initiated per-mention; no user-controlled loop. Anthropic rate limits are already caught and return None. PTB runs in a single async event loop — sleep is non-blocking |
| T-4-03 | Information Disclosure | bot reply saved to DB with sender_id=context.bot.id | accept | Bot's own Telegram user ID is not a secret; it is publicly visible to group members who can inspect bot profile |
| T-4-04 | Elevation of Privilege | persona name used as sender_name in save_message | accept | Persona name is a static string from the DB record set by the operator via seed.py — not controllable by group members |
| T-4-05 | Spoofing | is_mentioned persona name substring match | accept | False positives cause the bot to reply to messages containing the persona name by coincidence — this is acceptable and by design (persona name mention = intended address) |
</threat_model>

<verification>
Run full test suite after implementation:

  cd /Users/ismayilismayilov/Projects/misscaddybot && python -m pytest -x -q

Expected: all existing tests pass (45+ before this phase) plus 8 new tests = 53+ total.
Zero failures, zero errors.

Spot-check imports compile cleanly:
  python -c "from bot.handlers import get_context_messages, reply_to_mention, handle_message; print('OK')"
</verification>

<success_criteria>
1. python -m pytest -x -q passes with 53+ tests (45 prior + 8 new), zero failures
2. get_context_messages returns messages in chronological order with correct role mapping
3. reply_to_mention sends typing action before send_message in every test scenario
4. reply_to_mention does NOT call send_message when generate_reply returns None
5. reply_to_mention saves the bot's outgoing message to DB with is_bot=True
6. handle_message spawns asyncio.create_task(reply_to_mention(...)) on mention
7. Human verification: bot replies in-character with visible typing indicator in live group
</success_criteria>

<output>
After completion, create `.planning/4-1-SUMMARY.md` using the standard summary template.

Fields to populate:
  phase: 4
  plan: 1
  subsystem: handlers
  tags: [telegram, ptb, reactive-reply, typing-simulation, claude-api, async]
  dependency_graph:
    requires: [bot/handlers.py (existing), bot/ai.py, bot/database.py, bot/models.py]
    provides: [get_context_messages, reply_to_mention, updated handle_message]
    affects: []
  key_files:
    modified: [bot/handlers.py, tests/test_handlers.py]
</output>
