from dataclasses import dataclass
from datetime import datetime

import feedparser

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
]


@dataclass
class NewsItem:
    title: str
    link: str
    published: datetime | None
    source: str


def fetch_headlines(limit_per_feed: int = 15) -> list[NewsItem]:
    items: list[NewsItem] = []
    for feed_url in RSS_FEEDS:
        parsed = feedparser.parse(feed_url)
        source = parsed.feed.get("title", feed_url)
        for entry in parsed.entries[:limit_per_feed]:
            published = None
            if getattr(entry, "published_parsed", None):
                published = datetime(*entry.published_parsed[:6])
            items.append(
                NewsItem(
                    title=entry.get("title", ""),
                    link=entry.get("link", ""),
                    published=published,
                    source=source,
                )
            )
    items.sort(key=lambda i: i.published or datetime.min, reverse=True)
    return items
