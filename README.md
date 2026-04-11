# MissCaddyBot

> A Telegram group bot that feels like a real member — context-aware replies, autonomous messaging, and a fully customizable AI persona, powered by Claude, ChatGPT, or Grok.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Dashboard-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

---

## What Is It?

MissCaddyBot joins your Telegram group and participates like a real person. It reads every message, responds when mentioned or replied to, and even sends unprompted messages on its own schedule — all in your group's native language and tone.

The bot is built around a configurable **persona**: a name, background story, personality traits, and language style. It maintains a persistent memory of the group's conversations across restarts, and an admin web dashboard lets you tune everything without touching the database directly.

Originally built for a small Azerbaijani-speaking group, but works for any language or culture.

---

## Features

- **Mention & Reply Detection** — responds to `@username` tags, persona name mentions, and direct replies to its own messages
- **Context-Aware Replies** — fetches the last N messages and passes full conversation history to the AI model
- **Autonomous Messaging** — sends spontaneous messages on a randomized interval (configurable per group)
- **Persistent Memory** — saves all messages to PostgreSQL; memory survives bot restarts
- **Vector Memory Search** — extracts and embeds facts from conversations using pgvector for relevant context retrieval
- **Rolling Summaries** — automatically summarises older conversation chunks to keep token usage low
- **Prompt Caching** — caches system prompts via the Anthropic API, cutting effective token cost by ~10x
- **Multi-Provider AI** — switch between Anthropic Claude, OpenAI ChatGPT, or xAI Grok via a single env var
- **Per-Group Personas** — each group gets its own persona with individual settings and memory
- **Admin Dashboard** — FastAPI web UI for managing groups, editing personas, and viewing statistics
- **Auto-Seeding** — automatically creates a Group and Persona record when added to a new group
- **Human-Like Delays** — typing delay scaled to response length before sending

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Telegram Client | python-telegram-bot v21 (async) |
| AI Providers | Anthropic Claude, OpenAI, xAI Grok |
| Default Model | `claude-haiku-4-5-20251001` (cost-optimised) |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Vector Search | pgvector |
| Scheduler | APScheduler 3.x (AsyncIOScheduler) |
| Admin UI | FastAPI + Jinja2 + Uvicorn |
| Config | python-dotenv |
| Deployment | systemd on Ubuntu 24.04 |

---

## Architecture Overview

```
Telegram Group
      │
      ▼
┌─────────────────────────────────────────────┐
│              python-telegram-bot             │
│         (async update handler loop)          │
└───────────┬─────────────────────────────────┘
            │ message events
            ▼
┌─────────────────────────────────────────────┐
│                 handlers.py                  │
│  • Save message to DB                        │
│  • Detect mention / reply trigger            │
│  • Fetch context window from DB              │
│  • Call AI provider                          │
│  • Human-like typing delay                   │
│  • Send reply + save bot message to DB       │
└───────┬───────────────────────┬─────────────┘
        │                       │
        ▼                       ▼
┌───────────────┐     ┌─────────────────────┐
│  PostgreSQL   │     │     ai.py            │
│  • messages   │     │  Multi-provider:     │
│  • personas   │     │  Claude / GPT / Grok │
│  • summaries  │     │  + prompt caching    │
│  • memories   │     └─────────────────────┘
│  (pgvector)   │
└───────────────┘
        ▲
        │
┌───────────────────┐       ┌──────────────────────┐
│   scheduler.py    │       │   dashboard/app.py    │
│  • Auto-messages  │       │   FastAPI web UI      │
│  • Memory updates │       │   Persona editor      │
│  • Summaries      │       │   Group stats         │
└───────────────────┘       └──────────────────────┘
```

---

## Prerequisites

- Python 3.11+
- PostgreSQL 16 with the `pgvector` extension
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- At least one AI provider API key (Anthropic, OpenAI, or xAI)

---

## Quick Start

### 1. Clone and set up the environment

```bash
git clone https://github.com/ismayilov1995/misscaddybot.git
cd misscaddybot

python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env — see the Configuration section below
```

### 3. Set up PostgreSQL

```bash
# Create the database
createdb misscaddybot

# Enable pgvector extension (as superuser)
psql misscaddybot -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

The bot initialises all tables automatically on first run.

### 4. Seed the bot into a group

```bash
# Get your Telegram group's chat ID, then:
python seed.py --group-id -1001234567890 --title "My Group"
```

Or seed interactively with auto-detected defaults:

```bash
python seed.py --auto
```

### 5. Run the bot

```bash
python main.py
```

### 6. (Optional) Run the admin dashboard

```bash
python dashboard_server.py
# Dashboard available at http://localhost:8080
```

---

## Configuration

All configuration is done via the `.env` file. Copy `.env.example` and fill in the values.

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from BotFather |
| `BOT_USERNAME` | Yes | Bot username without `@` (e.g. `misscaddybot`) |
| `AI_PROVIDER` | Yes | `anthropic`, `openai`, or `grok` |
| `ANTHROPIC_API_KEY` | If using Claude | Anthropic API key |
| `OPENAI_API_KEY` | If using OpenAI | OpenAI API key |
| `XAI_API_KEY` | If using Grok | xAI API key |
| `AI_MODEL` | No | Override the default model for your provider |
| `DATABASE_URL` | Yes | PostgreSQL connection string (asyncpg format) |
| `DASHBOARD_SECRET_KEY` | No | Secret key for dashboard session cookies |
| `DASHBOARD_PASSWORD` | No | Admin password for the web dashboard |

**Example `.env`:**

```env
TELEGRAM_BOT_TOKEN=7123456789:AAH...
BOT_USERNAME=misscaddybot

AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/misscaddybot

DASHBOARD_SECRET_KEY=change-me-in-production
DASHBOARD_PASSWORD=admin
```

---

## Persona System

Each group has a `Persona` record that controls how the bot behaves. You can edit it via the admin dashboard or directly in the database.

| Field | Description |
|---|---|
| `name` | The bot's display name in the group |
| `bio` | Character backstory used in the system prompt |
| `personality` | Behavioral traits and communication guidelines |
| `language_style` | Language mix, slang level, emoji frequency |
| `memory` | Curated facts about the group (auto-updated every 24h) |
| `auto_message_enabled` | Whether the bot sends unprompted messages |
| `auto_message_interval_min` | Minimum minutes between autonomous messages |
| `auto_message_interval_max` | Maximum minutes between autonomous messages |
| `context_window` | Number of recent messages to include as context |

---

## Admin Dashboard

The FastAPI dashboard runs separately on port `8080` and provides:

- **Groups list** — all registered groups with message counts
- **Persona editor** — edit name, bio, personality, language style
- **Auto-message settings** — toggle and configure the scheduler per group
- **Conversation analysis** — temporal stats, context pairs, persona typology
- **Preset templates** — quick-apply pre-built persona configurations

```bash
python dashboard_server.py
```

Navigate to `http://localhost:8080` and log in with the `DASHBOARD_PASSWORD` from your `.env`.

---

## Project Structure

```
misscaddybot/
├── main.py                  # Entry point: initialise DB, scheduler, and bot
├── seed.py                  # CLI: create Group + Persona records
├── dashboard_server.py      # Entry point for the FastAPI admin dashboard
├── requirements.txt
├── .env.example
├── pytest.ini
│
├── bot/
│   ├── models.py            # SQLAlchemy ORM models
│   ├── database.py          # Async session factory and init_db()
│   ├── handlers.py          # Telegram update handlers
│   ├── ai.py                # Multi-provider AI abstraction
│   ├── scheduler.py         # APScheduler jobs
│   ├── memory.py            # pgvector fact extraction and retrieval
│   └── summary.py           # Rolling conversation summaries
│
├── dashboard/
│   ├── app.py               # FastAPI routes
│   ├── auth.py              # Session-based authentication
│   ├── presets.py           # Persona preset templates
│   └── templates/           # Jinja2 HTML templates
│       ├── base.html
│       ├── login.html
│       ├── groups.html
│       └── group_edit.html
│
├── systemd/
│   └── misscaddybot.service # systemd unit for VPS deployment
│
└── tests/
    ├── conftest.py
    ├── test_ai.py
    ├── test_database.py
    ├── test_handlers.py
    ├── test_models.py
    ├── test_seed.py
    └── test_startup.py
```

---

## Production Deployment (Ubuntu / DigitalOcean)

### 1. Provision the server

A $6/month DigitalOcean droplet (1 vCPU, 1 GB RAM, Ubuntu 24.04) is sufficient.

### 2. Install system dependencies

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip postgresql postgresql-contrib
sudo -u postgres psql -c "CREATE DATABASE misscaddybot;"
sudo -u postgres psql misscaddybot -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 3. Deploy the application

```bash
git clone https://github.com/ismayilov1995/misscaddybot.git /opt/misscaddybot
cd /opt/misscaddybot
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit /opt/misscaddybot/.env with production values
python seed.py --group-id <YOUR_CHAT_ID> --title "Your Group"
```

### 4. Configure systemd

```bash
sudo cp systemd/misscaddybot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now misscaddybot
```

### 5. Check status

```bash
sudo systemctl status misscaddybot
sudo journalctl -u misscaddybot -f
```

---

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_handlers.py -v
```

Tests use `pytest-asyncio` (configured in `pytest.ini`) and an in-memory SQLite database where applicable.

---

## Cost Estimate

Running MissCaddyBot in a moderately active group costs very little:

| Item | Monthly Cost |
|---|---|
| DigitalOcean $6 droplet | ~$6.00 |
| Claude Haiku API (with prompt caching) | ~$0.50–1.00 |
| PostgreSQL (local on VPS) | $0.00 |
| **Total** | **~$7–8/month** |

Prompt caching keeps the system prompt warm across the ~5-minute cache TTL, reducing effective token costs by approximately 10x compared to a naive implementation.

---

## Switching AI Providers

Change the `AI_PROVIDER` variable in `.env` and restart the bot:

```env
# Use Claude (default, recommended)
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Use OpenAI ChatGPT
AI_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Use xAI Grok
AI_PROVIDER=grok
XAI_API_KEY=xai-...
```

Vector embeddings (for the memory system) require OpenAI or Grok. When using Anthropic, the bot falls back to recency-based context retrieval automatically.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes and add tests
4. Ensure all tests pass: `pytest tests/ -v`
5. Commit with a clear message and open a pull request

---

## License

MIT License — see [LICENSE](LICENSE) for details.
