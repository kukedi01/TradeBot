from datetime import datetime

from app.market_data.kraken_client import kraken

# Kraken's public OHLC endpoint only ever returns the most recent ~720
# candles for a given timeframe, no matter how far back "since" points.
# So for longer lookbacks we need a coarser timeframe to stay within that
# cap, or we'd silently get truncated to the last ~30 days of hourly data.
MAX_CANDLES = 700


def pick_timeframe(days: int) -> str:
    if days * 24 <= MAX_CANDLES:
        return "1h"
    if days * 6 <= MAX_CANDLES:
        return "4h"
    if days <= MAX_CANDLES:
        return "1d"
    return "1w"


def fetch_historical_ohlcv(symbol: str, days: int = 30, timeframe: str | None = None) -> list[list]:
    timeframe = timeframe or pick_timeframe(days)
    since = kraken.milliseconds() - days * 24 * 60 * 60 * 1000
    return kraken.fetch_ohlcv(symbol, timeframe=timeframe, since=since)


def fetch_ohlcv_between(symbol: str, start: datetime, end: datetime, timeframe: str | None = None) -> list[list]:
    """Fetches candles for an explicit [start, end] window. Kraken has no
    "until" parameter, so we fetch from `start` and trim anything past `end`
    ourselves.

    The right timeframe depends on how far `start` is from *today*, not on
    the window's own length: Kraken always serves only its most recent
    ~700 candles for a timeframe, counting back from now. A since older
    than that reachable window returns nothing at all, even if the
    [start, end] window itself is short.
    """
    days_back_from_now = max((datetime.utcnow() - start).days, 1)
    timeframe = timeframe or pick_timeframe(days_back_from_now)
    since = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    candles = kraken.fetch_ohlcv(symbol, timeframe=timeframe, since=since)
    return [c for c in candles if c[0] <= end_ms]
