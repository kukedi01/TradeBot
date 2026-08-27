from datetime import datetime, timedelta

from app.backtest.data_loader import fetch_historical_ohlcv

LOOKBACK_DAYS = 90
CACHE_TTL = timedelta(hours=1)

# Above this weighted correlation with what's already held, a buy is
# considered "not really diversifying" -- adding to a coin that moves in
# lockstep with the rest of the portfolio increases concentration risk even
# though it looks like a new position.
HIGH_CORRELATION_THRESHOLD = 0.7
# Floor on how much a highly-correlated buy gets shrunk -- even at perfect
# correlation we still let the strategy act, just much smaller, rather than
# blocking it outright the way sentiment's pause_new_entries does.
MIN_SIZE_MULTIPLIER = 0.3

_cache: dict[str, dict[str, float]] | None = None
_cache_time: datetime | None = None
_cache_symbols: tuple[str, ...] | None = None


def returns_from_closes(closes: list[float]) -> list[float]:
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] != 0]


def _pearson(x: list[float], y: list[float]) -> float:
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    x, y = x[-n:], y[-n:]
    mean_x, mean_y = sum(x) / n, sum(y) / n
    covariance = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    variance_x = sum((xi - mean_x) ** 2 for xi in x)
    variance_y = sum((yi - mean_y) ** 2 for yi in y)
    denominator = (variance_x * variance_y) ** 0.5
    return covariance / denominator if denominator != 0 else 0.0


def compute_correlation_matrix_from_returns(returns_by_symbol: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    """The pure part of correlation computation, split out from the live
    fetch below so the backtest engine can feed it returns derived from its
    own historical candles instead of a live Kraken call."""
    symbols = list(returns_by_symbol.keys())
    matrix: dict[str, dict[str, float]] = {}
    for a in symbols:
        matrix[a] = {}
        for b in symbols:
            if a == b:
                matrix[a][b] = 1.0
            elif returns_by_symbol[a] and returns_by_symbol[b]:
                matrix[a][b] = _pearson(returns_by_symbol[a], returns_by_symbol[b])
            else:
                matrix[a][b] = 0.0
    return matrix


def _compute_correlation_matrix(symbols: list[str]) -> dict[str, dict[str, float]]:
    returns_by_symbol: dict[str, list[float]] = {}
    for symbol in symbols:
        try:
            candles = fetch_historical_ohlcv(symbol, days=LOOKBACK_DAYS)
            returns_by_symbol[symbol] = returns_from_closes([candle[4] for candle in candles])
        except Exception:
            # Kraken hiccup / rate limit -- treat this coin as uncorrelated
            # with everything rather than failing the whole matrix.
            returns_by_symbol[symbol] = []

    return compute_correlation_matrix_from_returns(returns_by_symbol)


def get_correlation_matrix(symbols: list[str]) -> dict[str, dict[str, float]]:
    """Cached the same way news sentiment is: recomputing this means 4
    historical-OHLCV fetches from Kraken, which is far more than a 30s
    trading tick should be doing on every cycle, and 90-day return
    correlations don't meaningfully shift within an hour anyway."""
    global _cache, _cache_time, _cache_symbols
    now = datetime.utcnow()
    key = tuple(symbols)
    if _cache is not None and _cache_time is not None and _cache_symbols == key and now - _cache_time < CACHE_TTL:
        return _cache
    _cache = _compute_correlation_matrix(symbols)
    _cache_time = now
    _cache_symbols = key
    return _cache


def correlation_size_multiplier(
    symbol: str,
    holdings: dict[str, float],
    prices: dict[str, float],
    correlation_matrix: dict[str, dict[str, float]],
) -> float:
    """How much to shrink a buy of `symbol` based on how correlated it is
    with the assets already held, weighted by how much of the portfolio
    each of those assets makes up. A buy that mostly just doubles down on
    the same market move as existing holdings gets sized down; a buy that
    diversifies into something uncorrelated is left alone."""
    held_value: dict[str, float] = {}
    total_held_value = 0.0
    for other_symbol, price in prices.items():
        if other_symbol == symbol:
            continue
        base_asset = other_symbol.split("/")[0]
        qty = holdings.get(base_asset, 0)
        value = qty * price
        if value > 0:
            held_value[other_symbol] = value
            total_held_value += value

    if total_held_value == 0:
        return 1.0

    weighted_correlation = sum(
        (value / total_held_value) * correlation_matrix.get(symbol, {}).get(other_symbol, 0.0)
        for other_symbol, value in held_value.items()
    )

    if weighted_correlation <= HIGH_CORRELATION_THRESHOLD:
        return 1.0

    span = 1.0 - HIGH_CORRELATION_THRESHOLD
    fraction_over = (weighted_correlation - HIGH_CORRELATION_THRESHOLD) / span
    return 1.0 - fraction_over * (1.0 - MIN_SIZE_MULTIPLIER)
