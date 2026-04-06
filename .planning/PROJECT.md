# MissCaddyBot

## What This Is

A Telegram bot that behaves as a real group member — reading messages, building context, and replying using Claude AI when mentioned or tagged. It also sends autonomous messages periodically to stay active in the conversation. The bot runs 24/7 on a DigitalOcean droplet via systemd with a PostgreSQL-backed memory so it can follow threads across restarts.

## Core Value

Replies feel authentically human — the Azerbaijani dialect, natural Russian/Turkish mix, and casual tone must pass as a real person in conversation.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Message ingestion — every group message saved to DB with sender info and timestamp
- [ ] Mention detection — reply when @username, persona name, or direct reply to bot's message
- [ ] Context-aware replies — fetch last N messages from DB, pass as conversation history to Claude
- [ ] Persona system — per-group Persona record defines character, language style, and behavior via DB
- [ ] Auto messages — APScheduler sends spontaneous messages on random interval (45–180 min)
- [ ] Prompt caching — system prompt cached via Anthropic `cache_control` to keep API cost under $1/month
- [ ] Seed script — CLI to create Group + Persona records with sensible defaults
- [ ] Systemd deployment — stable service on DigitalOcean $6 Droplet (Ubuntu 24.04), no Docker

### Out of Scope

- Admin dashboard / web UI — deferred to future milestone, DB edits are sufficient for MVP
- Chat export → persona generation — Phase 2 idea, not needed for v1
- Multiple simultaneous groups with different personas — single group focus for v1
- Voice/media message handling — text only for MVP
- Webhook mode — polling is fine for this scale

## Context

- Personal use: keeping a specific Telegram group engaged with a convincing AI persona
- The persona speaks primarily Azerbaijani (Baku dialect) with natural Russian/Turkish/English word mixing — multilingual casual style, short sentences, low emoji usage
- Target group: ~6 people, active 2-3 days/week, ~300-600 messages/active day, ~20 bot interactions/day
- Estimated monthly Claude API cost: $0.50–1.00 with prompt caching (DigitalOcean $6/mo is the real cost)
- No existing source code yet — PLAN.md contains the full technical spec

## Constraints

- **Tech Stack**: Python 3.11+, python-telegram-bot v21, SQLAlchemy 2.0 async, asyncpg, APScheduler 3.x — as specified in requirements.txt
- **AI Model**: claude-haiku-4-5-20251001 — cost-optimized for high-frequency bot replies
- **Database**: PostgreSQL 16 local on VPS — no managed DB services
- **Deploy**: systemd on Ubuntu 24.04 DigitalOcean droplet, no Docker
- **Budget**: Claude API must stay under ~$1/month — requires prompt caching on every call

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Polling over webhooks | Simpler setup, sufficient for small group scale | — Pending |
| Per-group Persona in DB | Allows future multi-group support without code changes | — Pending |
| claude-haiku over sonnet | Cost — haiku is 10x cheaper, sufficient for casual conversation | — Pending |
| Prompt caching on system prompt | System prompt is static and repeated every call — cache hits reduce cost by 10x | — Pending |
| No Docker | Less complexity for single-service VPS deploy | — Pending |

---

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-06 after initialization*
