# Feature Research

**Domain:** Telegram persona bot — AI human impersonation in group chat
**Researched:** 2026-04-06
**Confidence:** MEDIUM (training data + project spec; no live web access in this session)

---

## Context

This is not a generic chatbot. The goal is to make a small, tight-knit group (~6 people) believe
they are talking to a real human member named something like "Nicat." The primary failure mode is
not "the bot gave a wrong answer" — it is "the group suspects this is a bot." Every feature must
be evaluated through that lens.

The language target is Azerbaijani (Baku dialect) with natural Russian/Turkish/English code-switching,
short sentences, low emoji, and casual register.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features that must exist for the bot to feel like a real group member. Missing any of these
immediately breaks the illusion.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Reply on direct mention | Real members respond when called by name or @username | LOW | Must cover @username, persona name in text body, and Telegram reply-to-bot gestures |
| Context-aware replies | Real members know what was just said — replying without context reads as non-sequitur | MEDIUM | Last N messages as conversation history; 30 messages is reasonable sweet spot for cost vs quality |
| Persistent memory across restarts | Real members don't "forget" after going offline | LOW | DB-backed message log; not long-term episodic memory, just recent history |
| Natural reply latency (typing simulation) | Instant responses read as bot | LOW | `sendChatAction("typing")` + short random delay (1–4s) before sending |
| Short, casual response length | Real humans in group chat don't write essays | LOW | Max reply token cap ~80–150; prompt instruction for sentence-level brevity |
| Message ingestion (read everything) | A real member sees everything, not just messages to them | LOW | Requires Privacy Mode disabled; every group message saved to DB |
| Language/dialect consistency | Real members don't switch languages randomly | MEDIUM | System prompt must encode: Azerbaijani base + Russianisms + Turkish fillers + no formal constructs |
| No self-identification as bot | A human never announces they're an AI | LOW | Explicit hard instruction in system prompt; never say "as an AI…", never break character |
| Graceful handling of direct "are you a bot?" challenges | Real humans deny or deflect; a bot that admits kills the game | MEDIUM | Persona instruction: deflect with humor, deny, or redirect — never confirm |

### Differentiators (What Makes It Actually Convincing)

These are the features that separate "plausibly a slow typist" from "obviously a bot." The table
stakes keep the bot from failing; these make it succeed.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Autonomous message injection (auto-messages) | Real members initiate conversation, not just respond | MEDIUM | APScheduler with jittered 45–180 min intervals; prompt must ask for a contextually relevant opener, not random filler |
| Conversation-initiated vs. reply distinction | Real members sometimes just chime in, not replying to a specific message | LOW | Different prompt template for auto-messages (free commentary) vs. reactive replies (direct response) |
| Typing-speed realism | Time to "type" should correlate loosely with reply length | LOW | Delay = base_delay + (reply_char_count * 0.04 seconds), capped at ~8s |
| Code-switching fidelity | Baku dialect mixes AZ/RU/TR in specific patterns — random mixing sounds foreign | HIGH | Prompt must contain concrete examples: specific Russian filler words (короче, ну, давай), Turkish particles (yani, işte), Azerbaijani base grammar. Train-by-example in the system prompt |
| Persona-consistent opinions and interests | Real people have consistent views on topics | MEDIUM | `personality` DB field must encode specific stances: sports team, music taste, complaints, humor style |
| Typo and imperfection injection | Flawless grammar is a bot tell | MEDIUM | Occasional deliberate abbreviations (хз, лол, ок), dropped punctuation, lowercase-only messages |
| Reaction to group dynamics (memory of who said what) | Real members remember "oh that's what Fuad always says" | HIGH | Sender names in context history; prompt must reference them by name when relevant |
| Variable engagement pace | Real people go quiet for hours then burst with several messages | MEDIUM | Auto-message scheduler should have "quiet hours" concept and burst mode (1–2 messages close together occasionally) |
| Emoji restraint calibrated to persona | Overuse or underuse of emoji signals non-human patterns | LOW | Hard constraint: 0–1 emoji per message, specific set of acceptable ones defined in persona |
| Reply threading (responding to reply chains, not just latest msg) | Real members follow who replied to whom | MEDIUM | Include `replied_to_id` in context rendering so Claude understands reply structure |

### Anti-Features (Things That Make Bots Feel Obviously Robotic)

These are patterns that seem helpful or natural to add but actively destroy the human illusion.

| Feature | Why It Seems Good | Why It Kills the Illusion | What to Do Instead |
|---------|-------------------|---------------------------|-------------------|
| Bullet-point or numbered-list replies | Organized, clear | No human sends bullet lists in group chat | Hard-prohibit in system prompt; prose only, single sentence preferred |
| Long contextual summaries ("so you're saying…") | Shows comprehension | Humans don't narrate their understanding in casual chat | React directly; skip meta-commentary |
| Formal register fallback | LLMs default to polite/formal when uncertain | Sounds like customer service bot | Prompt must enumerate specific informal patterns to default to |
| Uniform reply length | Easier to implement | Real humans vary: sometimes one word, sometimes a paragraph | Allow length to vary; short replies for agreement/acknowledgment, longer for actual opinions |
| Always replying to every mention immediately | Responsive | Real people miss messages, delay, read-but-don't-reply | Introduce occasional (rare) non-reply: ~10% skip rate on low-urgency mentions via probabilistic check |
| Hedging language ("I think," "maybe," "it depends") | Sounds thoughtful | Baku casual speech is direct and confident | Persona instruction: state opinions directly; hedging is a formal register marker |
| Timestamps showing bot online 24/7 | Maximum availability | Real humans have sleep schedules | Auto-message quiet hours (e.g. 01:00–08:00 Baku time, UTC+4); reduce reply speed during off-hours |
| Perfect spelling and grammar | Looks professional | Baku group chat has typos, abbreviations, slang | Explicitly allow and prompt for minor imperfections |
| Asking clarifying questions | Good chatbot practice | Sounds like a help desk | Guess intent and respond to what was most likely meant; only ask if genuinely ambiguous |
| Overuse of the persona name in replies | Feels personalized | "Hey Fuad, I think…" is not how friends talk | Avoid addressing members by name unless emphasis is natural |

---

## Feature Dependencies

```
Message Ingestion
    └──required by──> Context-Aware Replies
    └──required by──> Reply Threading
    └──required by──> Mention Detection

Mention Detection
    └──required by──> Reply on Direct Mention
    └──enhances──> Reply Threading

Persona System (DB record)
    └──required by──> Language/Dialect Consistency
    └──required by──> Persona-Consistent Opinions
    └──required by──> Code-Switching Fidelity
    └──required by──> Auto-Message Injection

Auto-Message Injection
    └──enhances──> Variable Engagement Pace
    └──requires──> Message Ingestion (for context)
    └──requires──> Quiet Hours Config

Typing Simulation
    └──enhances──> Natural Reply Latency
    └──enhances──> Typing-Speed Realism
    └──independent of──> Context-Aware Replies

Reply Threading
    └──enhances──> Context-Aware Replies
    └──requires──> Message Ingestion (replied_to_id stored)
```

### Dependency Notes

- **Message Ingestion is the root dependency:** everything that makes the bot contextually aware
  depends on having a complete, ordered message history in the DB. This must be Phase 1.

- **Persona System gates language quality:** without the DB-encoded persona (bio, personality,
  language_style), the LLM will default to generic assistant behavior. Persona must be defined
  before the bot sends a single reply.

- **Auto-messages require context to not sound random:** an auto-message generator that doesn't
  read recent conversation produces non-sequitur messages that instantly break immersion. It must
  share the same context-fetch path as reactive replies.

- **Typing simulation is independent but high ROI:** it requires no DB changes and no LLM
  integration — just a `sendChatAction` call and `asyncio.sleep`. It should be added alongside
  the first working reply, not deferred.

- **Reply threading enhances but doesn't block:** the bot is convincing without it, but noticeably
  better with it. `replied_to_id` storage costs nothing at ingestion time — store it even if the
  display logic comes later.

---

## MVP Definition

### Launch With (v1)

These are the features required to open the bot in a real group and not be immediately detected.

- [ ] Message ingestion with sender context — bot needs to "see" the whole room
- [ ] Mention detection (username + persona name + reply-to-bot) — the primary trigger
- [ ] Context-aware reactive reply — last 30 messages as history to Claude
- [ ] Persona system in DB — language style, personality, bio all encoded before first message
- [ ] Natural reply latency — typing action + random 1–4s delay, always
- [ ] Auto-message scheduler — jittered 45–180 min; uses same context fetch as reactive reply
- [ ] Short reply enforcement — max_tokens cap + system prompt instruction
- [ ] Language/dialect consistency — Azerbaijani + RU/TR code-switch examples baked into persona prompt
- [ ] Hard "never admit to being a bot" instruction in persona

### Add After Validation (v1.x)

Add these once the bot is live and the core illusion holds for at least one week.

- [ ] Typing-speed realism (delay proportional to reply length) — quick win, pure python-telegram-bot
- [ ] Quiet hours for auto-messages — prevents suspicious 3am messages
- [ ] Occasional non-reply (10% skip on low-signal mentions) — adds human texture
- [ ] Burst mode (two auto-messages close together once/session) — adds human irregularity
- [ ] Reply threading context (render replied_to chains in history) — meaningful for active threads

### Future Consideration (v2+)

Defer until v1 is validated and group members are genuinely fooled.

- [ ] Chat export → persona generation — import real user's historical messages to generate persona
- [ ] Admin dashboard — DB edits are sufficient for v1
- [ ] Multi-group, multi-persona — single group is the entire target audience for now
- [ ] Long-term episodic memory (facts about group members) — requires separate memory layer
- [ ] Media/voice message awareness — text-only is fine for this group

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Message ingestion | HIGH | LOW | P1 |
| Mention detection | HIGH | LOW | P1 |
| Context-aware replies | HIGH | LOW | P1 |
| Persona system in DB | HIGH | LOW | P1 |
| Natural reply latency (typing sim) | HIGH | LOW | P1 |
| Auto-message scheduler | HIGH | MEDIUM | P1 |
| Short reply enforcement | HIGH | LOW | P1 |
| Language/dialect prompt design | HIGH | MEDIUM | P1 |
| "Never admit bot" instruction | HIGH | LOW | P1 |
| Reply threading context | MEDIUM | LOW | P2 |
| Typing-speed realism | MEDIUM | LOW | P2 |
| Quiet hours | MEDIUM | LOW | P2 |
| Occasional non-reply (skip logic) | MEDIUM | LOW | P2 |
| Burst auto-message mode | LOW | LOW | P2 |
| Chat export → persona generation | HIGH | HIGH | P3 |
| Long-term episodic memory | HIGH | HIGH | P3 |
| Multi-group support | LOW | MEDIUM | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when core is stable
- P3: Nice to have, future milestone

---

## Competitor / Reference Analysis

No direct public competitors for Azerbaijani-dialect persona bots. The following reference classes
inform the feature set:

| Reference Class | What They Get Right | Where They Fail | Our Approach |
|-----------------|---------------------|-----------------|--------------|
| Generic Telegram chatbots (BotFather-type) | Reliable mention detection, command handling | Generic English, never autonomous, clearly bot-like | Drop command interface entirely; no /commands |
| LLM-powered group bots (general) | Good language quality | Formal register, bullet points, over-eager to help | Restrict register, inject imperfections, limit helpfulness |
| Role-play / character bots (Character.ai style) | Personality consistency, character memory | Typically English, fantasy-register, not Telegram-native | Port the persona-anchoring approach to Telegram group context |
| Human-coded sock puppet accounts | Fully convincing when well-operated | Manual, not scalable, operator fatigue | Automate the 80% (replies, openers) while matching their style patterns |

---

## Critical Design Notes

### The System Prompt Is the Product

For a persona bot, the system prompt is not configuration — it is the core product artifact. The
language style section in particular needs concrete examples, not abstract instructions.

Bad: "Speak Azerbaijani with some Russian words."
Good: "You speak primarily Azerbaijani but naturally drop in Russian filler words like 'короче',
'ну типо', 'давай', and Turkish fillers like 'yani', 'işte'. You say 'хз' instead of 'bilmirəm'.
You never use formal Azerbaijani verb endings. You write in lowercase unless emphasizing something."

### Context Window is a Cost/Quality Tradeoff

- 10 messages: cheap, misses thread continuity, bot seems forgetful
- 30 messages: good balance at ~1500 tokens (project target)
- 50 messages: noticeably better for long threads, ~2500 tokens, roughly 2x cost
- 100+ messages: diminishing returns for casual group chat

Recommendation: 30 for v1. Make it configurable per-persona so it can be tuned after observing
real conversation patterns.

### Probabilistic Behaviors Require Careful Calibration

Skip-reply logic (10% chance of not responding to a low-signal mention) and burst mode (occasional
double message) must be tuned empirically. Starting values:
- Non-reply skip: 10% on messages that contain persona name but no question mark
- Burst: 5% chance that an auto-message is followed by a second one 3–8 minutes later

Too much randomness reads as unreliable; too little reads as mechanical.

---

## Sources

- Project spec: `/Users/ismayilismayilov/Projects/misscaddybot/PLAN.md`
- Project context: `/Users/ismayilismayilov/Projects/misscaddybot/.planning/PROJECT.md`
- Domain knowledge: Telegram Bot API behavior (training data, HIGH confidence for stable APIs)
- Human impersonation patterns: synthesis from chatbot research, Turing test literature, and
  community observations about bot detection in group chats (MEDIUM confidence — behavioral)
- Azerbaijani/Baku dialect code-switching: linguistic training data on South Caucasus multilingual
  register (MEDIUM confidence — verify specific examples with a native speaker)

**Confidence assessment by area:**
- Telegram API capabilities (mention detection, typing action, message types): HIGH
- LLM prompt engineering for persona consistency: HIGH
- Human impersonation behavioral features (what reads as bot): MEDIUM
- Specific Baku dialect patterns: MEDIUM (validate with native speaker before finalizing system prompt)

---

*Feature research for: Telegram persona bot / human impersonation in group chat*
*Researched: 2026-04-06*
