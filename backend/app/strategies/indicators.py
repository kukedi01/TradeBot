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
