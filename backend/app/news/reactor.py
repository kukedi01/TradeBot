from dataclasses import dataclass
from datetime import datetime, timedelta

from app.news.fetcher import fetch_headlines
from app.news.sentiment import score_headline

# Below this average sentiment, the bot pauses new buys entirely.
PAUSE_THRESHOLD = -0.3
# Below this, it also refuses to sell into a shrinking sell-side move (severe panic).
SEVERE_THRESHOLD = -0.6

CACHE_TTL = timedelta(minutes=5)


@dataclass
class SentimentState:
    avg_sentiment: float
    headline_count: int
    pause_new_entries: bool
    size_multiplier: float


_cache: SentimentState | None = None
_cache_time: datetime | None = None


def _compute_sentiment_state() -> SentimentState:
    headlines = fetch_headlines()
    if not headlines:
        return SentimentState(avg_sentiment=0.0, headline_count=0, pause_new_entries=False, size_multiplier=1.0)

    scores = [score_headline(item.title) for item in headlines]
    avg = sum(scores) / len(scores)

    if avg <= SEVERE_THRESHOLD:
        pause_new_entries, size_multiplier = True, 0.25
    elif avg <= PAUSE_THRESHOLD:
        pause_new_entries, size_multiplier = True, 0.5
    else:
        pause_new_entries, size_multiplier = False, 1.0

    return SentimentState(
        avg_sentiment=avg,
        headline_count=len(headlines),
        pause_new_entries=pause_new_entries,
        size_multiplier=size_multiplier,
    )


def get_sentiment_state() -> SentimentState:
    global _cache, _cache_time
    now = datetime.utcnow()
    if _cache is not None and _cache_time is not None and now - _cache_time < CACHE_TTL:
        return _cache
    _cache = _compute_sentiment_state()
    _cache_time = now
    return _cache
