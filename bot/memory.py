# bot/memory.py
"""
Group memory backed by PostgreSQL + pgvector.

Embedding provider follows AI_PROVIDER env var:
  - openai     → text-embedding-3-small (1536 dim default)
  - grok       → xAI embedding endpoint (OpenAI-compatible)
  - anthropic  → no embedding API; facts stored without vector,
                 retrieved by recency instead of similarity

Flow:
  1. Every MEMORY_UPDATE_INTERVAL messages, extract facts from recent
     conversation via AI and store them in group_memories.
  2. Before each bot reply, retrieve the top-K most relevant facts
     (by cosine similarity if embeddings available, otherwise by recency)
     and inject them into the system prompt.
"""

import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Group, GroupMemory, Message

logger = logging.getLogger(__name__)

MEMORY_UPDATE_INTERVAL = int(os.getenv("MEMORY_UPDATE_INTERVAL", "20"))
MEMORY_TOP_K = int(os.getenv("MEMORY_TOP_K", "6"))

_EXTRACTION_SYSTEM = (
    "Sən bir Telegram qrupunun yaddaş sistemisin. "
    "Sənə qrup söhbətindən mesajlar veriləcək. "
    "Aşağıdakı növ faktları çıxar — bunlar botun qrup üzvlərini tanımasına kömək edəcək:\n"
    "- Üzv xarakteristikası: 'Ruslan həmişə gecə aktivdir', 'İsmayıl çox zarafat edir'\n"
    "- Münasibətlər: 'Ruslan ilə Firudin tez-tez dalaşır', 'İsmayıl hər şeyə razılaşır'\n"
    "- Inside joke-lar: qrupda təkrarlanan zarafatlar, ləqəblər, xatırlatmalar\n"
    "- Qrupun maraqları: tez-tez nə müzakirə edirlər\n"
    "- Danışıq tərzi: kim necə yazır, hansı sözləri işlədir\n"
    "Hər fakt ayrı sətirdə, '- ' ilə başlasın. Maksimum 10 fakt. "
    "Qısa və konkret yaz. Yalnız faktları yaz."
)


# ---------------------------------------------------------------------------
# Embedding — provider-aware
# ---------------------------------------------------------------------------

def _provider() -> str:
    return os.getenv("AI_PROVIDER", "openai").lower()


def _embedding_provider() -> str:
    """
    Provider used specifically for embeddings.
    Defaults to AI_PROVIDER, but can be overridden with EMBEDDING_PROVIDER.

    Example hybrid setup:
      AI_PROVIDER=anthropic      # Claude for chat
      EMBEDDING_PROVIDER=openai  # OpenAI for embeddings (since Anthropic has no embedding API)
    """
    return os.getenv("EMBEDDING_PROVIDER", _provider()).lower()


async def get_embedding(text_input: str) -> list[float] | None:
    """
    Get embedding vector using the configured embedding provider.

    - openai    → OpenAI embeddings API (OPENAI_API_KEY)
    - grok      → xAI embeddings API (XAI_API_KEY), OpenAI-compatible
    - anthropic → returns None (no embedding API; memory falls back to recency)
    """
    provider = _embedding_provider()
    if provider == "anthropic":
        return None
    if provider == "grok":
        return await _embed_grok(text_input)
    return await _embed_openai(text_input)


async def _embed_openai(text_input: str) -> list[float] | None:
    try:
        import openai
    except ImportError:
        logger.error("openai package not installed")
        return None
    model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    client = openai.AsyncOpenAI()  # reads OPENAI_API_KEY automatically
    try:
        response = await client.embeddings.create(model=model, input=text_input)
        return response.data[0].embedding
    except Exception as e:
        logger.warning("OpenAI embedding failed: %s", e)
        return None


async def _embed_grok(text_input: str) -> list[float] | None:
    try:
        import openai
    except ImportError:
        logger.error("openai package not installed")
        return None
    model = os.getenv("EMBEDDING_MODEL", "embedding-3")
    client = openai.AsyncOpenAI(
        api_key=os.getenv("XAI_API_KEY"),
        base_url="https://api.x.ai/v1",
    )
    try:
        response = await client.embeddings.create(model=model, input=text_input)
        return response.data[0].embedding
    except Exception as e:
        logger.warning("Grok embedding failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Fact extraction — uses the same AI provider as chat
# ---------------------------------------------------------------------------

async def _extract_facts_via_ai(context_messages: list[dict]) -> list[str]:
    lines = []
    for m in context_messages:
        role = "Bot" if m["role"] == "assistant" else "İstifadəçi"
        lines.append(f"{role}: {m['content']}")
    user_content = f"Söhbət:\n" + "\n".join(lines) + "\n\nFaktları çıxar:"

    provider = _provider()
    if provider == "anthropic":
        raw = await _call_anthropic(user_content)
    elif provider == "grok":
        raw = await _call_grok(user_content)
    else:
        raw = await _call_openai(user_content)

    if not raw:
        return []
    facts = []
    for line in raw.splitlines():
        line = line.strip().lstrip("- ").strip()
        if line:
            facts.append(line)
    return facts[:10]


def _memory_model() -> str:
    """Model used for fact extraction. Defaults to MEMORY_MODEL, then AI_MODEL."""
    provider = _provider()
    if provider == "anthropic":
        return os.getenv("MEMORY_MODEL", os.getenv("AI_MODEL", "claude-haiku-4-5-20251001"))
    if provider == "grok":
        return os.getenv("MEMORY_MODEL", os.getenv("AI_MODEL", "grok-3-mini"))
    return os.getenv("MEMORY_MODEL", os.getenv("AI_MODEL", "gpt-4o-mini"))


async def _call_openai(user_content: str) -> str | None:
    try:
        import openai
    except ImportError:
        return None
    client = openai.AsyncOpenAI()
    model = _memory_model()
    try:
        resp = await client.chat.completions.create(
            model=model,
            max_tokens=300,
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM},
                {"role": "user", "content": user_content},
            ],
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.warning("Fact extraction (openai) failed: %s", e)
        return None


async def _call_grok(user_content: str) -> str | None:
    try:
        import openai
    except ImportError:
        return None
    client = openai.AsyncOpenAI(
        api_key=os.getenv("XAI_API_KEY"),
        base_url="https://api.x.ai/v1",
    )
    model = _memory_model()
    try:
        resp = await client.chat.completions.create(
            model=model,
            max_tokens=300,
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM},
                {"role": "user", "content": user_content},
            ],
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.warning("Fact extraction (grok) failed: %s", e)
        return None


async def _call_anthropic(user_content: str) -> str | None:
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.AsyncAnthropic()
    model = _memory_model()
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=300,
            system=_EXTRACTION_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        return resp.content[0].text
    except Exception as e:
        logger.warning("Fact extraction (anthropic) failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

async def store_facts(
    session: AsyncSession,
    group_id: int,
    facts: list[str],
) -> None:
    """
    Embed each fact and store in group_memories.

    If embeddings are available (openai/grok): skip near-duplicates via cosine distance.
    If embeddings are unavailable (anthropic): store facts as plain text, no dedup.
    """
    for fact in facts:
        embedding = await get_embedding(fact)

        if embedding is not None:
            # Skip if a very similar fact already exists
            result = await session.execute(
                select(GroupMemory.id).where(
                    GroupMemory.group_id == group_id,
                    GroupMemory.embedding.cosine_distance(embedding) < 0.08,
                ).limit(1)
            )
            if result.scalar_one_or_none() is not None:
                logger.debug("Skipping near-duplicate fact: %s", fact[:60])
                continue

        session.add(GroupMemory(group_id=group_id, fact=fact, embedding=embedding))

    await session.commit()


async def retrieve_relevant_memories(
    session: AsyncSession,
    group_id: int,
    query_text: str,
    top_k: int = MEMORY_TOP_K,
) -> list[str]:
    """
    Return top-k facts for this group.

    With embeddings (openai/grok): semantic cosine similarity search.
    Without embeddings (anthropic): most recent facts by insertion order.
    """
    embedding = await get_embedding(query_text)

    if embedding is not None:
        result = await session.execute(
            select(GroupMemory.fact)
            .where(
                GroupMemory.group_id == group_id,
                GroupMemory.embedding.is_not(None),
            )
            .order_by(GroupMemory.embedding.cosine_distance(embedding))
            .limit(top_k)
        )
    else:
        result = await session.execute(
            select(GroupMemory.fact)
            .where(GroupMemory.group_id == group_id)
            .order_by(GroupMemory.id.desc())
            .limit(top_k)
        )

    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def maybe_update_memory(
    group: Group,
    context_messages: list[dict],
) -> None:
    """
    Extract facts and store them if total message count is a multiple of
    MEMORY_UPDATE_INTERVAL. Opens its own DB session — safe as asyncio.create_task().
    """
    from sqlalchemy import func
    from bot.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        count_result = await session.execute(
            select(func.count()).where(Message.group_id == group.id)
        )
        total = count_result.scalar() or 0

        if total == 0 or total % MEMORY_UPDATE_INTERVAL != 0:
            return

        logger.info(
            "Updating group memory for group %d (total messages: %d)",
            group.telegram_id,
            total,
        )

        facts = await _extract_facts_via_ai(context_messages)
        if facts:
            await store_facts(session, group.id, facts)
            logger.info("Stored %d new facts for group %d", len(facts), group.telegram_id)


async def get_memory_context(
    session: AsyncSession,
    group_id: int,
    recent_messages: list[dict],
) -> str:
    """
    Build a memory string to inject into the system prompt.
    Uses the last few user messages as the semantic query.
    """
    user_texts = [
        m["content"] for m in recent_messages[-5:] if m["role"] == "user"
    ]
    if not user_texts:
        return ""

    query = " ".join(user_texts)
    facts = await retrieve_relevant_memories(session, group_id, query)
    if not facts:
        return ""

    lines = "\n".join(f"- {f}" for f in facts)
    return f"Bu qrup haqqında bildiklərin:\n{lines}"
