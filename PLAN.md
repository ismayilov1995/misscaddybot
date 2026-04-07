# MissCaddyBot — Telegram Persona Bot

## Project Overview

A Telegram bot that behaves like a real group member. It reads group messages, builds context, and replies using Claude AI when mentioned or tagged. It also sends autonomous messages periodically to stay active in the conversation. The bot has a persistent memory via PostgreSQL so it can follow conversation threads across sessions.

The bot will be deployed on a DigitalOcean Droplet (Ubuntu 24.04) without Docker, managed via systemd.

---

## Tech Stack

- **Language:** Python 3.11+
- **Telegram:** python-telegram-bot v21 (async)
- **AI:** Anthropic Claude API (claude-haiku-4-5-20251001)
- **Database:** PostgreSQL 16 (local on VPS)
- **ORM:** SQLAlchemy 2.0 async + asyncpg
- **Scheduler:** APScheduler 3.x (AsyncIOScheduler)
- **Config:** python-dotenv
- **Deploy:** systemd service, no Docker

---

## Project Structure

```
misscaddybot/
├── main.py                  # Entry point, wires everything together
├── seed_persona.py          # CLI script to insert initial persona into DB
├── requirements.txt
├── .env.example
├── systemd/
│   └── misscaddybot.service # systemd unit file for VPS deploy
└── bot/
    ├── __init__.py
    ├── models.py            # SQLAlchemy models: Group, Persona, Message
    ├── memory.py            # DB read/write helpers
    ├── ai.py                # Claude API calls + prompt builders
    ├── handlers.py          # Telegram update handlers
    └── scheduler.py         # APScheduler auto-message job
```

---

## Database Schema

### Group
- `id` int PK
- `telegram_id` bigint unique — Telegram chat ID
- `title` varchar
- `is_active` bool default true
- `created_at` datetime

### Persona
- `id` int PK
- `group_id` FK → Group (unique — one persona per group)
- `name` varchar — bot's display name in prompts (e.g. "Nicat")
- `bio` text — short character description
- `personality` text — character traits, behavior guidelines
- `language_style` text — language mix, slang level, emoji usage
- `auto_message_enabled` bool default true
- `auto_message_interval_min` int (minutes) default 45
- `auto_message_interval_max` int (minutes) default 180
- `context_window` int default 50 — how many recent messages to include in prompt
- `created_at` / `updated_at` datetime

### Message
- `id` int PK
- `group_id` FK → Group
- `telegram_message_id` bigint
- `sender_id` bigint — Telegram user ID
- `sender_name` varchar
- `sender_username` varchar nullable
- `text` text
- `is_bot` bool — true if sent by our bot
- `replied_to_id` bigint nullable — message_id this is a reply to
- `sent_at` datetime

---

## Core Features

### 1. Message Ingestion
Every text message in the group is saved to the `messages` table with sender info and timestamp. Bot's own messages are also saved with `is_bot=true`.

### 2. Mention Detection
The bot replies when:
- Its Telegram username is tagged (`@MissCaddyBot`)
- Its persona name appears in the message text
- Someone replies directly to one of its messages

### 3. Context-Aware Replies
Before generating a reply, the bot fetches the last N messages (defined by `context_window`) from DB and formats them as a conversation history. This is passed to Claude along with the system prompt.

Default `context_window` is 30 messages (not 50) to balance context quality vs token cost.

### 4. Persona System
Each group has one `Persona` record. The persona fields are used to build the Claude system prompt:
- Bot is instructed to act as a real human, never reveal it's a bot
- Language: primarily Azerbaijani (Baku dialect), with natural Russian/Turkish/English word mixing — multilingual casual style
- Short, natural replies — no formal or overly long responses

### 5. Auto Messages (Scheduler)
APScheduler runs a job every N minutes (random interval between `auto_message_interval_min` and `auto_message_interval_max`). For each active group with `auto_message_enabled=true`, it:
- Fetches recent context
- Asks Claude to generate a short spontaneous message fitting the conversation
- Sends it to the group
- Saves it to DB

### 6. Seed Script
`seed_persona.py` is a CLI script that:
- Takes group Telegram ID and title as input
- Creates Group + Persona records with sensible defaults
- Default persona: young Baku male, casual Azerbaijani with Russian words mixed in, low emoji usage, short sentences

---

## Prompt Caching

Use Anthropic's prompt caching to reduce token costs. The system prompt (persona definition) is static and repeated on every API call — cache it.

### How to implement in `ai.py`:

Every API call to Claude must use `cache_control` on the system prompt block:

```python
response = await client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=300,
    system=[
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"}  # Cache this block
        }
    ],
    messages=messages,
)
```

The `ephemeral` cache lives for 5 minutes. Since the bot receives messages continuously in an active group, the cache will stay warm and the system prompt tokens will cost 10x less on cache hits.

### Cost breakdown (our use case):
- Group: 6 people, active 2-3 days/week, ~300-600 messages/active day
- Bot replies: ~20 interactions/active day (mentions + auto messages)
- Tokens per call: ~300 (system) + ~1500 (context 30 msgs) + ~100 (reply) = ~1900 tokens
- With caching: system prompt cached after first call → ~1600 tokens effective
- **Estimated monthly cost: ~$0.50–1.00** (DigitalOcean $6/mo is the real cost)

---

## Environment Variables (.env)

```
TELEGRAM_BOT_TOKEN=        # From BotFather
BOT_USERNAME=misscaddybot  # Without @
ANTHROPIC_API_KEY=         # Anthropic API key
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/misscaddybot
```

---

## Deployment (DigitalOcean, no Docker)

### systemd service file: `systemd/misscaddybot.service`
```ini
[Unit]
Description=MissCaddyBot Telegram Persona Bot
After=network.target postgresql.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/misscaddybot
EnvironmentFile=/home/ubuntu/misscaddybot/.env
ExecStart=/home/ubuntu/misscaddybot/venv/bin/python main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Deploy steps (document in README.md):
1. SSH into droplet
2. Install Python 3.11, PostgreSQL 16
3. Create DB and user
4. Clone repo, create venv, pip install
5. Copy .env, fill values
6. Run `python seed_persona.py`
7. Copy systemd file, enable and start service

---

## Out of Scope for MVP

- Admin dashboard / SvelteKit web UI
- Chat export → persona generation (Faz 2)
- Multiple simultaneous groups with different personas
- Voice/media message handling
- Webhook mode (polling is fine for MVP)

---

## Success Criteria

- Bot joins group, reads all messages (Privacy Mode disabled)
- Replies naturally when mentioned or tagged
- Sends autonomous messages every 45–180 minutes
- Persists message history across restarts
- Runs stable on DigitalOcean $6 Droplet via systemd
- Persona is editable directly in DB for now (dashboard later)
