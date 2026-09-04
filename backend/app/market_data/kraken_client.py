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
