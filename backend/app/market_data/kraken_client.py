import time

import ccxt

# Explicit timeout (ms) -- without one a hung connection (e.g. a laptop
# sleep/wake cycle breaking an in-flight request) can block far longer than
# is useful for a 30s trading tick.
kraken = ccxt.kraken({"timeout": 15000})


def get_ticker_price(symbol: str) -> float:
    ticker = kraken.fetch_ticker(symbol)
    return ticker["last"]


def get_ticker_volume(symbol: str) -> float:
    """24h base-currency trading volume -- a separate call from
    get_ticker_price rather than a combined one, since most call sites only
    ever need the price and this keeps that path unchanged."""
    ticker = kraken.fetch_ticker(symbol)
    return ticker.get("baseVolume") or 0.0


def get_daily_high_low(symbol: str) -> tuple[float, float]:
    """Today's (UTC calendar day) high/low, read from Kraken's raw ticker
    payload rather than ccxt's normalized high/low fields -- Kraken's own
    ticker response carries both today's and the trailing-24h figures as a
    2-element array (`h`/`l`, index 0 = today), and ccxt's normalized
    'high'/'low' don't reliably preserve that distinction."""
    ticker = kraken.fetch_ticker(symbol)
    info = ticker.get("info", {})
    high = info.get("h")
    low = info.get("l")
    if high and low:
        return float(high[0]), float(low[0])
    return float(ticker.get("high") or 0.0), float(ticker.get("low") or 0.0)


_OVERVIEW_CACHE: dict[str, tuple[float, dict]] = {}
_OVERVIEW_TTL_SECONDS = 30


def get_market_overview(symbol: str) -> dict:
    """Price, today's high/low and the 24h change from a single ticker call.

    Cached for 30s because the dashboard refreshes every 5s across 4 coins --
    uncached that would be ~48 Kraken calls a minute for figures that move far
    more slowly than that, and it would compete with the trading tick for the
    same rate limit.
    """
    now = time.time()
    cached = _OVERVIEW_CACHE.get(symbol)
    if cached is not None and now - cached[0] < _OVERVIEW_TTL_SECONDS:
        return cached[1]

    ticker = kraken.fetch_ticker(symbol)
    info = ticker.get("info", {})
    high = info.get("h")
    low = info.get("l")
    last = ticker.get("last")

    # ccxt normally fills `percentage`, but it's derived from the open price
    # and can come back empty; Kraken's raw payload carries today's opening
    # price as `o`, so fall back to computing it rather than showing nothing.
    change_pct = ticker.get("percentage")
    if change_pct is None:
        opening = info.get("o")
        if opening and last:
            opening = float(opening[0]) if isinstance(opening, list) else float(opening)
            if opening:
                change_pct = (last - opening) / opening * 100

    overview = {
        "symbol": symbol,
        "price": last,
        "change_pct_24h": change_pct,
        "daily_high": float(high[0]) if high else ticker.get("high"),
        "daily_low": float(low[0]) if low else ticker.get("low"),
    }
    _OVERVIEW_CACHE[symbol] = (now, overview)
    return overview
