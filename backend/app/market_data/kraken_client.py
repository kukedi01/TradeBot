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
