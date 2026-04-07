# Requirements: MissCaddyBot

**Defined:** 2026-04-06
**Core Value:** Replies feel authentically human — the Azerbaijani dialect, natural Russian/Turkish mix, and casual tone must pass as a real person in conversation.

## v1 Requirements

### Message Handling

- [ ] **MSG-01**: Bot saves every incoming group text message to DB with sender ID, name, username, timestamp, and replied_to_id
- [ ] **MSG-02**: Bot saves its own outgoing messages to DB with `is_bot=true`
- [ ] **MSG-03**: Bot detects when it is mentioned (via @username, persona name in text body, or direct reply to a bot message) and triggers a reply

### Reactive Replies

- [ ] **REPLY-01**: Bot fetches the last N messages (configurable per-persona `context_window`, default 30) from DB before each reply
- [ ] **REPLY-02**: Bot sends `sendChatAction("typing")` and waits a random delay (1–4s) before every reply
- [ ] **REPLY-03**: Bot delays proportional to reply length (base_delay + char_count × 0.04s, capped at 8s) for typing-speed realism
- [ ] **REPLY-04**: Bot replies are short and casual (max ~150 tokens enforced via max_tokens + system prompt)
- [ ] **REPLY-05**: Bot replies use Azerbaijani base with natural Russian/Turkish/English code-switching as defined by persona language_style

### Persona System

- [x] **PERS-01**: Each Telegram group has one Persona record in DB (name, bio, personality, language_style, context_window, auto_message settings)
- [x] **PERS-02**: Claude system prompt is constructed from Persona fields for every API call
- [x] **PERS-03**: System prompt includes hard instruction to never identify as a bot, deflect/deny if asked directly
- [x] **PERS-04**: Seed script creates Group + Persona records with sensible defaults from CLI input (group Telegram ID + title)

### Autonomous Messaging

- [ ] **AUTO-01**: Scheduler sends spontaneous auto-messages at random intervals (configurable min/max per Persona, default 45–180 min)
- [ ] **AUTO-02**: Auto-messages use same context-fetch path as reactive replies (last N messages for relevance)
- [ ] **AUTO-03**: Auto-messages are sent only to groups where `auto_message_enabled=true`

### AI Integration

- [ ] **AI-01**: Claude API calls use `cache_control: {"type": "ephemeral"}` on the system prompt block for every request
- [ ] **AI-02**: Claude API errors (rate limits, timeouts, API errors) are handled gracefully — bot does not crash; failed reply is silently dropped
- [ ] **AI-03**: Model is configurable via environment/config (default: claude-haiku-4-5-20251001)

### Deployment

- [ ] **DEPLOY-01**: Bot runs as a systemd service on Ubuntu 24.04 with `Restart=on-failure` and `RestartSec=10`
- [x] **DEPLOY-02**: All secrets (Telegram token, Anthropic key, DB URL) are loaded from `.env` file via python-dotenv
- [x] **DEPLOY-03**: Database schema is initialized via SQLAlchemy `create_all()` on startup (Alembic migrations added as follow-up)

## v2 Requirements

### Human Texture

- **HUMAN-01**: Auto-messages respect quiet hours (no autonomous messages 01:00–08:00 Baku time, UTC+4)
- **HUMAN-02**: Occasional non-reply (10% skip rate on low-signal mentions that contain persona name but no question mark)
- **HUMAN-03**: Burst mode — 5% chance that an auto-message is followed by a second one 3–8 minutes later
- **HUMAN-04**: Reply threading — render replied_to chains in context history so Claude understands reply structure

### Operations

- **OPS-01**: Alembic migrations for schema changes (instead of manual SQL on VPS)
- **OPS-02**: Structured logging with timestamps for production debugging

## Out of Scope

| Feature | Reason |
|---------|--------|
| Admin dashboard / web UI | DB edits are sufficient for v1; high complexity, deferred to v2+ |
| Chat export → persona generation | Phase 2 idea; requires separate ML pipeline |
| Multi-group, multi-persona management | Single group is the v1 target; schema already supports it for v2 |
| Voice/media message handling | Text-only is sufficient for this group |
| Webhook mode | Polling is adequate for small group scale |
| Long-term episodic memory | Complex separate memory layer; 30-message context window is sufficient |
| Bullet-point/list replies | Anti-feature — immediately signals bot behavior; hard-prohibited in system prompt |
| Command interface (/commands) | Anti-feature — humans don't use /commands in casual chat |
| Clarifying questions | Anti-feature — sounds like help desk; bot should guess and respond |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| MSG-01 | — | Pending |
| MSG-02 | — | Pending |
| MSG-03 | — | Pending |
| REPLY-01 | — | Pending |
| REPLY-02 | — | Pending |
| REPLY-03 | — | Pending |
| REPLY-04 | — | Pending |
| REPLY-05 | — | Pending |
| PERS-01 | 1 | Complete |
| PERS-02 | — | Complete |
| PERS-03 | — | Complete |
| PERS-04 | — | Complete |
| AUTO-01 | — | Pending |
| AUTO-02 | — | Pending |
| AUTO-03 | — | Pending |
| AI-01 | — | Pending |
| AI-02 | — | Pending |
| AI-03 | — | Pending |
| DEPLOY-01 | — | Pending |
| DEPLOY-02 | 1 | Complete |
| DEPLOY-03 | 1 | Complete |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 0 (updated during roadmap creation)
- Unmapped: 21 ⚠️ (pending roadmap)

---
*Requirements defined: 2026-04-06*
*Last updated: 2026-04-06 after initial definition*
