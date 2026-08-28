import ssl
from dataclasses import dataclass
from datetime import datetime

import certifi
import feedparser

# feedparser fetches over plain urllib, which uses Python's own default SSL
# context rather than whatever CA bundle other libraries (requests, ccxt)
# already trust. On a python.org macOS install that context has no CA certs
# wired up at all until "Install Certificates.command" is run manually --
# without this, every feed fetch fails with CERTIFICATE_VERIFY_FAILED and
# silently returns zero entries (feedparser reports it via `bozo`, not an
# exception), so the news panel just looks permanently empty.
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

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
