# MissCaddyBot

> A Telegram group bot that feels like a real member — context-aware replies, autonomous messaging, voice messages, emoji reactions, and a fully customizable AI persona, powered by Claude, ChatGPT, or Grok.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Dashboard-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

---

## What Is It?

MissCaddyBot joins your Telegram group and participates like a real person. It reads every message, responds when mentioned or replied to, reacts with emojis, occasionally sends voice messages, and even fires off unprompted messages on its own schedule — all in your group's native language and tone.

The bot is built around a configurable **persona**: a name, background story, personality traits, and language style. It maintains a layered memory of the group's conversations (short-term summaries, medium-term meta-summaries, and long-term vector facts) across restarts. An admin web dashboard lets you tune everything without touching the database.

Originally built for a small Azerbaijani-speaking group, but works for any language or culture.

---

## Features

### 🧠 Intelligence & Memory
- **Mention & Reply Detection** — responds to `@username` tags, persona name mentions, and direct replies
- **Context-Aware Replies** — fetches the last N messages and passes full conversation history to the AI
- **Hierarchical Rolling Summaries** — two-level summary system:
  - **L1** (short-term): summaries of recent message batches, two sections: group portrait + recent events
  - **L2** (medium-term): meta-summary generated every 4 L1s — captures deep group dynamics over time
- **Vector Memory** — extracts and embeds facts from conversations (pgvector) for semantic retrieval
- **Quick-Teach** — store facts directly via chat: `@bot yadda saxla Kick = Ruslandır`
- **Prompt Caching** — caches system prompts via Anthropic API, cutting token cost ~10x

### 🎭 Human-Like Behaviour
- **Emoji Reactions** — reacts to ~12% of all messages (contextual: 😂 for funny, 🔥 for cool, 🤔 for questions) without typing a reply
- **Message Splitting** — 28% of replies are broken into 2–3 short messages with natural typing gaps, sometimes prefixed with "hə", "bir dəq", "aha"
- **Delayed Replies** — 7% chance to "miss" a mention and reply 5–45 min later with "Bağışla indi gördüm"
- **Circadian Rhythm** — shorter replies and sleepier tone at night (1–7 AM), peak energy in afternoon
- **Typos & Self-Correction** — 8% chance to introduce a realistic keyboard typo followed by a correction
- **Follow-Up Conversations** — 25% chance to continue active conversations without being tagged
- **Conversation Starters** — 20% of auto-messages open a new topic organically
- **Dynamic Response Length** — max tokens randomised 150–450 (or 40–120 at night, 200–500 at peak)
- **Human-Like Typing Delay** — delay scaled to response length before sending

### 🎙️ Voice Messages
- **Edge TTS** — free Microsoft neural voices via `edge-tts`, no API cost
- **Native Azerbaijani Voices** — `az-AZ-BanuNeural` (female) and `az-AZ-BabekNeural` (male)
- **Gender-Aware Selection** — detects `[Qadın]` / `[Kişi]` prefix in persona bio
- **Prosody Randomisation** — randomised rate (−5% to +10%) and pitch (−3Hz to +5Hz) per message
- **Configurable Chance** — voice chance set per persona from dashboard (0–30%)
- **Force Voice** — send "səslə", "sesle", or "voice" in your message to force a voice reply

### 🤖 Multi-Provider AI
- **Supported Providers** — Anthropic Claude, OpenAI ChatGPT, xAI Grok
- **Automatic Grok-3 Fallback** — if the primary AI refuses content (content-policy refusal detected in az/en/ru), automatically retries with Grok-3 (full model, most permissive)
- **Per-Group Language** — choose bot reply language per group: 🇦🇿 Azerbaijani / 🇷🇺 Russian / 🇬🇧 English

### 📊 Autonomous Messaging
- **Scheduled Auto-Messages** — sends spontaneous messages on a configurable randomised interval per group
- **Per-Group Intervals** — min/max configurable from dashboard (default 45–180 min)

### 🖥️ Admin Dashboard
- **Persona Editor** — name, bio, personality, language style, voice chance, reply language
- **Preset Templates** — quick-apply pre-built persona configs (Elon, Trump, Joe Rogan, Nicat)
- **Group Statistics** — message counts, member activity, temporal patterns
- **Character Analysis** — deep AI-powered persona analysis: context pairs, typology, trends, vector facts
- **Member Analysis** — per-member character analysis from conversation history

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Telegram Client | python-telegram-bot v21 (async) |
| AI Providers | Anthropic Claude, OpenAI, xAI Grok |
| Fallback Model | Grok-3 (automatic on refusal) |
| TTS | edge-tts (Microsoft Azure Neural, free) |
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
      │  (messages, reactions)
      ▼
┌─────────────────────────────────────────────────────────┐
│                  python-telegram-bot                     │
│              (async update handler loop)                 │
└───────────┬─────────────────────────────────────────────┘
            │ message events
            ▼
┌─────────────────────────────────────────────────────────┐
│                     handlers.py                          │
│  • Save message to DB                                    │
│  • Emoji reaction (12% of all messages, async)           │
│  • Detect mention / reply / teach command                │
│  • Delayed reply decision (7% chance)                    │
│  • Fetch context window + summary context + memory       │
│  • Circadian mood hint + token adjustment                │
│  • Call AI provider (with Grok-3 fallback)               │
│  • Multi-message split (28%) + typo injection (8%)       │
│  • Human-like typing delay → send reply                  │
│  • Save bot message to DB                                │
│  • Async: update memory + generate summary               │
└───────┬────────────────────────────┬────────────────────┘
        │                            │
        ▼                            ▼
┌───────────────┐          ┌─────────────────────────────┐
│  PostgreSQL   │          │          ai.py               │
│  • messages   │          │  Primary: Claude/GPT/Grok    │
│  • personas   │          │  Fallback: Grok-3 on refusal │
│  • summaries  │          └─────────────────────────────┘
│    (L1 + L2)  │
│  • memories   │          ┌─────────────────────────────┐
│  (pgvector)   │          │         tts.py               │
└───────────────┘          │  Edge TTS, az-AZ voices      │
        ▲                  │  Prosody randomisation        │
        │                  └─────────────────────────────┘
┌───────────────────┐       ┌──────────────────────────┐
│   scheduler.py    │       │    dashboard/app.py       │
│  • Auto-messages  │       │    FastAPI web UI         │
│  • Conv starters  │       │    Persona editor         │
│  • L1/L2 summary  │       │    Character analysis     │
└───────────────────┘       └──────────────────────────┘
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
createdb misscaddybot
psql misscaddybot -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Tables are created automatically on first run.

### 4. Run the bot

```bash
python main.py
```

### 5. (Optional) Run the admin dashboard

```bash
python dashboard_server.py
# Dashboard available at http://localhost:8080
```

---

## Configuration

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from BotFather |
| `BOT_USERNAME` | Yes | Bot username without `@` |
| `AI_PROVIDER` | Yes | `anthropic`, `openai`, or `grok` |
| `ANTHROPIC_API_KEY` | If using Claude | Anthropic API key |
| `OPENAI_API_KEY` | If using OpenAI | OpenAI API key |
| `XAI_API_KEY` | Recommended | xAI key — also used for Grok-3 fallback |
| `AI_MODEL` | No | Override the default model |
| `DATABASE_URL` | Yes | PostgreSQL connection string (asyncpg) |
| `DASHBOARD_SECRET_KEY` | No | Secret for dashboard session cookies |
| `DASHBOARD_PASSWORD` | No | Admin password for the web dashboard |
| `VOICE_CHANCE` | No | Default voice reply chance 0.0–1.0 (default: `0.08`) |
| `REACTION_CHANCE` | No | Emoji reaction chance 0.0–1.0 (default: `0.12`) |
| `SUMMARY_MODEL` | No | Model for summary generation (default: provider's mini model) |
| `L2_TRIGGER_COUNT` | No | L1 summaries needed to trigger L2 (default: `4`) |
| `MEMORY_UPDATE_INTERVAL` | No | Messages between memory extraction runs (default: `20`) |

**Example `.env`:**

```env
TELEGRAM_BOT_TOKEN=7123456789:AAH...
BOT_USERNAME=misscaddybot

AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
XAI_API_KEY=xai-...          # enables Grok-3 fallback even when AI_PROVIDER=anthropic

DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/misscaddybot

DASHBOARD_SECRET_KEY=change-me-in-production
DASHBOARD_PASSWORD=admin
```

---

## Persona System

Each group has a `Persona` record. Edit via the dashboard or directly in the database.

| Field | Description |
|---|---|
| `name` | Display name in the group |
| `bio` | Character backstory — prefix `[Qadın]` or `[Kişi]` for TTS gender selection |
| `personality` | Behavioural traits and communication guidelines |
| `language_style` | Language mix, slang level, emoji frequency |
| `language` | Reply language: `az` (Azerbaijani), `ru` (Russian), `en` (English) |
| `voice_chance` | % chance to reply with a voice message (0–30, default 8) |
| `auto_message_enabled` | Whether the bot sends unprompted messages |
| `auto_message_interval_min` | Minimum minutes between autonomous messages |
| `auto_message_interval_max` | Maximum minutes between autonomous messages |
| `context_window` | Number of recent messages to include as context |
| `memory` | Curated facts about the group (auto-updated every 24h) |

### Voice gender detection

Prefix the `bio` field to select the TTS voice:

```
[Qadın] 24 yaşlı Bakılı qız...   →  az-AZ-BanuNeural  (female)
[Kişi]  26 yaşlı Bakılı oğlan... →  az-AZ-BabekNeural (male)
```

---

## Quick-Teach Command

Store facts directly from the chat — no dashboard needed:

```
@bot yadda saxla Kick əslində Ruslandır
@bot remember: tomorrow is İsmayıl's birthday
Nicat yaddaş: Firudin hər gecə saat 2-də aktivdir
```

The bot replies with "Yadda saxladım 👍" and the fact is stored with deduplication.

---

## Memory Architecture

```
Raw Messages
    │
    ├─▶  L1 Summary (every bot tag)
    │       • QRUP PORTRETİ — who is who, relationships, inside jokes
    │       • SON SÖHBƏT    — what happened in this batch (always fresh)
    │
    └─▶  L2 Meta-Summary (every 4 L1s)
            • Deep group portrait across many sessions
            • Recurring themes, relationship dynamics, group spirit

Bot reply context = L2 + recent L1s + raw messages + vector facts
```

Vector facts (pgvector) are extracted every 20 messages and retrieved via cosine similarity search at reply time.

---

## Grok-3 Automatic Fallback

When the primary AI model refuses to respond (content-policy refusal detected in Azerbaijani, English, or Russian), the bot silently retries with **Grok-3** (full model) using the exact same context and persona:

```
Primary AI → "edə bilmirəm..." → detected as refusal
                                        ↓
                              Grok-3 (full model)
                                        ↓
                              Natural reply ✅
```

Requires `XAI_API_KEY` to be set. If `AI_PROVIDER=grok` is already configured, no retry is made.

---

## Project Structure

```
misscaddybot/
├── main.py                  # Entry point: DB init, scheduler, bot
├── seed.py                  # CLI: create Group + Persona records
├── dashboard_server.py      # FastAPI admin dashboard entry point
├── requirements.txt
├── .env.example
│
├── bot/
│   ├── models.py            # SQLAlchemy ORM models
│   ├── database.py          # Async session factory and init_db()
│   ├── handlers.py          # Telegram update handlers
│   ├── ai.py                # Multi-provider AI + Grok-3 fallback
│   ├── scheduler.py         # APScheduler jobs (auto-message, memory)
│   ├── memory.py            # pgvector fact extraction and retrieval
│   ├── summary.py           # Hierarchical L1/L2 rolling summaries
│   ├── tts.py               # Edge TTS voice message generation
│   ├── reactions.py         # Passive emoji reactions
│   └── humanize.py          # Message splitting, delays, typos, circadian
│
├── dashboard/
│   ├── app.py               # FastAPI routes + character analysis
│   ├── auth.py              # Session-based authentication
│   ├── presets.py           # Persona preset templates
│   └── templates/           # Jinja2 HTML templates
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

### 1. Install system dependencies

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip postgresql postgresql-contrib
sudo -u postgres psql -c "CREATE DATABASE misscaddybot;"
sudo -u postgres psql misscaddybot -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 2. Deploy

```bash
git clone https://github.com/ismayilov1995/misscaddybot.git /opt/misscaddybot
cd /opt/misscaddybot
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with production values
```

### 3. Configure systemd

```bash
sudo cp systemd/misscaddybot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now misscaddybot misscaddy-dashboard
```

### 4. Database migrations (when updating an existing install)

```bash
# After git pull, run any new column additions:
psql "postgresql://postgres:PASSWORD@localhost:5432/misscaddybot" \
  -c "ALTER TABLE personas ADD COLUMN IF NOT EXISTS voice_chance INTEGER NOT NULL DEFAULT 8;"
psql "postgresql://postgres:PASSWORD@localhost:5432/misscaddybot" \
  -c "ALTER TABLE personas ADD COLUMN IF NOT EXISTS language VARCHAR(10) NOT NULL DEFAULT 'az';"
psql "postgresql://postgres:PASSWORD@localhost:5432/misscaddybot" \
  -c "ALTER TABLE group_summaries ADD COLUMN IF NOT EXISTS level INTEGER NOT NULL DEFAULT 1;"
```

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Cost Estimate

| Item | Monthly Cost |
|---|---|
| DigitalOcean $6 droplet | ~$6.00 |
| Claude Haiku + prompt caching | ~$0.50–1.00 |
| Edge TTS (voice messages) | $0.00 (free) |
| PostgreSQL (local) | $0.00 |
| **Total** | **~$7–8/month** |

---

## Switching AI Providers

```env
# Anthropic Claude (recommended, prompt caching supported)
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
XAI_API_KEY=xai-...   # keep this for Grok-3 fallback

# OpenAI ChatGPT
AI_PROVIDER=openai
OPENAI_API_KEY=sk-...

# xAI Grok
AI_PROVIDER=grok
XAI_API_KEY=xai-...
```

> **Note:** Vector embeddings require OpenAI or Grok. With Anthropic, the bot automatically falls back to recency-based memory retrieval.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
