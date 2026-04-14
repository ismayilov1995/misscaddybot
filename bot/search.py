# bot/search.py
"""
Real-time web search via DuckDuckGo (no API key required).

When someone asks about current events, prices, scores, or recent news,
the bot searches the web and injects results as context before replying.
This gives it knowledge beyond its training cutoff.

Requires: pip install duckduckgo-search
"""

import logging

logger = logging.getLogger(__name__)

# Keywords that suggest the user wants current/real-time information
_SEARCH_TRIGGERS = [
    # Azerbaijani
    "bu gün", "bu gun", "indi nə", "indi ne", "son xəbər", "son xeber",
    "nə vaxt", "ne vaxt", "kim qazandı", "kim qazandi",
    "neçədir", "nececdir", "hava necədir", "hava nece",
    "kurs neçədir", "kurs nece", "dollar neçə", "dollar nece",
    "nə oldu", "ne oldu", "axırıncı", "axirinci",
    "ən son", "en son", "son nəticə", "son netice",
    "bu həftə", "bu hefte", "bu ay", "bu il",
    "hazırda", "hazirda", "indiki", "canlı", "canli",
    # English (common in group chats)
    "latest", "today", "right now", "current", "live score",
    "what happened", "news",
]


def needs_search(text: str) -> bool:
    """Return True if the message likely needs real-time information."""
    lower = text.lower()
    return any(trigger in lower for trigger in _SEARCH_TRIGGERS)


async def search_web(query: str, max_results: int = 3) -> str | None:
    """
    Search DuckDuckGo and return a formatted context string.

    Returns None if search fails or no results found.
    The returned string is suitable for injection into memory_context.
    """
    try:
        from duckduckgo_search import AsyncDDGS

        async with AsyncDDGS() as ddgs:
            results = await ddgs.atext(query, max_results=max_results)

        if not results:
            logger.debug("No search results for: %s", query[:60])
            return None

        lines = ["🔍 İnternetdən tapılan məlumat:"]
        for r in results:
            title = r.get("title", "").strip()
            body = r.get("body", "").strip()[:180]
            if title or body:
                lines.append(f"• {title}: {body}" if title else f"• {body}")

        context = "\n".join(lines)
        logger.debug("Search results for '%s': %d chars", query[:40], len(context))
        return context

    except ImportError:
        logger.warning("duckduckgo-search not installed — run: pip install duckduckgo-search")
        return None
    except Exception as e:
        logger.warning("Web search failed for '%s': %s", query[:60], e)
        return None
