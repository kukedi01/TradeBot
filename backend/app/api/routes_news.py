from fastapi import APIRouter

from app.news.fetcher import fetch_headlines
from app.news.reactor import get_sentiment_state
from app.news.sentiment import score_headline

router = APIRouter(prefix="/news", tags=["news"])


@router.get("")
def get_news():
    headlines = fetch_headlines()
    items = [
        {
            "title": item.title,
            "link": item.link,
            "published": item.published.isoformat() if item.published else None,
            "source": item.source,
            "sentiment": score_headline(item.title),
        }
        for item in headlines
    ]
    avg_sentiment = sum(i["sentiment"] for i in items) / len(items) if items else 0.0
    return {"items": items, "avg_sentiment": avg_sentiment}


@router.get("/sentiment")
def get_sentiment():
    state = get_sentiment_state()
    return {
        "avg_sentiment": state.avg_sentiment,
        "headline_count": state.headline_count,
        "pause_new_entries": state.pause_new_entries,
        "size_multiplier": state.size_multiplier,
    }
