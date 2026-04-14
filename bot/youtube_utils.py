# bot/youtube_utils.py
"""
YouTube video understanding — fetch transcripts for shared YouTube links.

When someone shares a YouTube link, this module fetches the video's
transcript (if available) so the bot can comment on the actual content,
not just the title.

Requires: pip install youtube-transcript-api
"""

import logging
import re

logger = logging.getLogger(__name__)

# Matches youtube.com/watch?v=, youtu.be/, and youtube.com/shorts/
_YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/|youtube\.com/shorts/)"
    r"([A-Za-z0-9_-]{11})"
)


def extract_video_id(url: str) -> str | None:
    """Extract the 11-character YouTube video ID from a URL."""
    m = _YOUTUBE_RE.search(url)
    return m.group(1) if m else None


async def get_youtube_transcript(url: str) -> str | None:
    """
    Fetch the transcript for a YouTube video.

    Tries languages in order: az, en, ru, tr, auto-generated.
    Returns plain text (up to 2000 chars), or None if unavailable.

    YouTubeTranscriptApi is sync — runs in executor to avoid blocking.
    """
    video_id = extract_video_id(url)
    if not video_id:
        return None

    try:
        from youtube_transcript_api import (
            YouTubeTranscriptApi,
            TranscriptsDisabled,
            NoTranscriptFound,
        )
        import asyncio

        def _fetch() -> str | None:
            try:
                segments = YouTubeTranscriptApi.get_transcript(
                    video_id,
                    languages=["az", "en", "ru", "tr"],
                )
            except (TranscriptsDisabled, NoTranscriptFound):
                # Try auto-generated transcript as fallback
                try:
                    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                    transcript = transcript_list.find_generated_transcript(["az", "en", "ru", "tr"])
                    segments = transcript.fetch()
                except Exception:
                    return None

            text = " ".join(seg["text"] for seg in segments)
            return text[:2000] if text else None

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _fetch)
        if result:
            logger.debug("YouTube transcript fetched for %s (%d chars)", video_id, len(result))
        return result

    except ImportError:
        logger.warning("youtube-transcript-api not installed — run: pip install youtube-transcript-api")
        return None
    except Exception as e:
        logger.debug("YouTube transcript failed for %s: %s", video_id, e)
        return None


def format_youtube_context(title: str, transcript: str | None) -> str:
    """
    Format YouTube metadata + transcript for injection into AI context.

    Returns a string like:
      Video: "Title here"
      Məzmun: first 400 chars of transcript...
    """
    parts = []
    if title:
        parts.append(f'Video: "{title}"')
    if transcript:
        snippet = transcript[:400]
        if len(transcript) > 400:
            snippet += "..."
        parts.append(f"Məzmun: {snippet}")
    return "\n".join(parts)
