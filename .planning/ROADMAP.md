# Roadmap: MissCaddyBot

## Overview

MissCaddyBot ships in five phases that build on each other in strict dependency order. Phase 1 lays the data foundation — DB models, session factory, and environment config. Phase 2 establishes the persona system that gates every Claude call. Phase 3 wires message ingestion so the bot sees everything in the group. Phase 4 delivers the full reactive reply loop — context fetch, typing simulation, Claude integration, and persona voice. Phase 5 closes the loop with autonomous scheduled messaging and production systemd deployment.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - DB models, session factory, env/config, and schema initialization
- [ ] **Phase 2: Persona System** - Persona DB record, seed CLI, Claude system prompt construction, bot identity
- [ ] **Phase 3: Message Ingestion** - Save all group messages and bot messages; detect mentions
- [ ] **Phase 4: Reactive Replies** - Context-aware Claude replies with typing simulation and persona voice
- [ ] **Phase 5: Autonomous Messaging and Deployment** - APScheduler auto-messages and systemd production service

## Phase Details

### Phase 1: Foundation
**Goal**: The project runs, connects to PostgreSQL, and all ORM models exist with correct async session configuration
**Depends on**: Nothing (first phase)
**Requirements**: DEPLOY-02, DEPLOY-03, PERS-01
**Success Criteria** (what must be TRUE):
  1. `python main.py` starts without error and connects to the local PostgreSQL database
  2. All DB tables (Group, Persona, Message) are created on first run via `create_all()`
  3. Secrets (Telegram token, Anthropic key, DB URL) are read from `.env` — the bot refuses to start if any are missing
  4. `async_sessionmaker` is configured with `expire_on_commit=False` — no `MissingGreenlet` errors on attribute access after commit
**Plans**: TBD

### Phase 2: Persona System
**Goal**: A Persona record exists in the DB that fully defines the bot's character, and the Claude system prompt is correctly constructed from that record on every call
**Depends on**: Phase 1
**Requirements**: PERS-02, PERS-03, PERS-04
**Success Criteria** (what must be TRUE):
  1. Running `python seed.py` creates a Group and Persona record for a given Telegram group ID and title
  2. Claude system prompt is assembled from Persona fields (name, bio, personality, language_style) and used on every AI call
  3. System prompt contains a hard instruction that the bot must never admit to being a bot, deflect or deny if asked directly
  4. System prompt can be verified by printing it — it reads as a believable human persona profile, not a chatbot description
**Plans**: TBD
**UI hint**: no

### Phase 3: Message Ingestion
**Goal**: Every group message and every bot reply is saved to the DB; the bot can detect when it is being addressed
**Depends on**: Phase 2
**Requirements**: MSG-01, MSG-02, MSG-03
**Success Criteria** (what must be TRUE):
  1. Every plain group text message appears in the `messages` table with correct sender ID, name, username, timestamp, and `replied_to_id`
  2. Bot's own outgoing messages are saved to the DB with `is_bot=true`
  3. Bot detects a mention when addressed via @username, persona name in message body, or direct reply to a bot message — verified by seeing it queue a reply in all three cases
  4. Privacy Mode is confirmed disabled in BotFather — plain group messages (not just commands) fill the messages table
**Plans**: TBD

### Phase 4: Reactive Replies
**Goal**: When mentioned, the bot fetches recent conversation history, calls Claude with the persona system prompt and cached system block, and replies in-character with realistic typing simulation
**Depends on**: Phase 3
**Requirements**: REPLY-01, REPLY-02, REPLY-03, REPLY-04, REPLY-05, AI-01, AI-02, AI-03
**Success Criteria** (what must be TRUE):
  1. Bot reply always shows a typing indicator before sending and waits a 1–4s random base delay
  2. Bot reply delay scales with reply length (chars × 0.04s, capped at 8s) — longer replies take longer to appear
  3. Bot replies are short and casual — enforced by `max_tokens` cap (~150) and system prompt instruction; no bullet points, no formal structure
  4. Claude API calls use `cache_control: {"type": "ephemeral"}` on the system prompt block — confirmed via Anthropic console cache hit rate
  5. Claude API errors (rate limit, timeout, connection error) are caught silently — the bot does not crash and the group sees no error message
  6. Model is loaded from environment/config (defaults to `claude-haiku-4-5-20251001`) — swappable without code changes
**Plans**: 1 plan
Plans:
- [ ] 4-PLAN.md — Implement get_context_messages, reply_to_mention, update handle_message to spawn reply task
**UI hint**: no

### Phase 5: Autonomous Messaging and Deployment
**Goal**: The bot sends contextually relevant spontaneous messages at random intervals and runs as a stable 24/7 systemd service on the DigitalOcean droplet
**Depends on**: Phase 4
**Requirements**: AUTO-01, AUTO-02, AUTO-03, DEPLOY-01
**Success Criteria** (what must be TRUE):
  1. Bot sends a spontaneous message to the group without any mention — observed within the configured interval window (default 45–180 min)
  2. Auto-messages are only sent to groups where `auto_message_enabled=true` in the Persona record
  3. Auto-messages use the same context-fetch path as reactive replies — the message references recent conversation, not generic filler
  4. `systemctl status misscaddybot` shows the service as `active (running)` after a VPS reboot
  5. If the bot process crashes, systemd restarts it within 10 seconds (`Restart=on-failure`, `RestartSec=10`)
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 1/1 | Complete | 2026-04-07 |
| 2. Persona System | 1/1 | Complete | 2026-04-07 |
| 3. Message Ingestion | 0/? | Not started | - |
| 4. Reactive Replies | 0/1 | Not started | - |
| 5. Autonomous Messaging and Deployment | 0/? | Not started | - |
