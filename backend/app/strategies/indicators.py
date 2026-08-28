import pandas as pd


def sma(prices: list[float], period: int) -> float | None:
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def rsi(prices: list[float], period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    series = pd.Series(prices[-(period + 1) :])
    delta = series.diff().dropna()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.mean()
    avg_loss = losses.mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def bollinger_bands(prices: list[float], period: int = 20, num_std: float = 2.0):
    """Returns (upper, middle, lower) bands, or (None, None, None) if there
    isn't enough history yet. The middle band is just the SMA; the outer
    bands widen and narrow with recent volatility."""
    if len(prices) < period:
        return None, None, None
    window = prices[-period:]
    middle = sum(window) / period
    variance = sum((p - middle) ** 2 for p in window) / period
    std = variance**0.5
    return middle + num_std * std, middle, middle - num_std * std


def rsi_series(prices: list[float], period: int = 14) -> list[float | None]:
    """RSI computed at every point in the history (not just the latest), so
    it can be charted as a line -- each entry uses only the prices up to
    that point, same as the strategies themselves only ever see the past."""
    return [rsi(prices[: i + 1], period) for i in range(len(prices))]


def _ema_series(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return [None] * len(values)
    multiplier = 2 / (period + 1)
    result: list[float | None] = [None] * (period - 1)
    seed = sum(values[:period]) / period
    result.append(seed)
    prev = seed
    for value in values[period:]:
        prev = (value - prev) * multiplier + prev
        result.append(prev)
    return result


def macd_series(
    prices: list[float], fast_period: int = 6, slow_period: int = 13, signal_period: int = 5
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Returns (macd_line, signal_line, histogram), each the same length as
    `prices`, with None entries until there's enough history.

    Standard MACD (12/26/9) needs ~35 points before the signal line ever
    produces a value -- more than the ~30-tick rolling window the live
    session keeps. These shorter periods are chosen specifically so a real
    signal line is possible within that window; they're a faster-reacting
    variant, not the textbook default, and are labeled as such wherever
    they're shown.
    """
    fast_ema = _ema_series(prices, fast_period)
    slow_ema = _ema_series(prices, slow_period)
    macd_line = [f - s if f is not None and s is not None else None for f, s in zip(fast_ema, slow_ema)]

    valid_macd = [m for m in macd_line if m is not None]
    signal_valid = _ema_series(valid_macd, signal_period) if len(valid_macd) >= signal_period else []
    missing = len(macd_line) - len(signal_valid)
    signal_line: list[float | None] = [None] * missing + signal_valid

    histogram = [
        m - s if m is not None and s is not None else None for m, s in zip(macd_line, signal_line)
    ]
    return macd_line, signal_line, histogram
