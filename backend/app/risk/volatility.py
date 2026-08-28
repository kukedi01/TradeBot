import statistics

# How many of the most recent points count as "right now" vs the whole
# available window as the baseline.
SHORT_WINDOW = 5
# Below this many return points, there isn't enough history to compare a
# short window against a baseline meaningfully, so no adjustment is made.
MIN_RETURNS = 10

# How far this can shrink a buy when the asset is unusually choppy right
# now, and how far it can grow one when it's unusually calm.
MIN_MULTIPLIER = 0.4
MAX_MULTIPLIER = 1.3


def _returns(prices: list[float]) -> list[float]:
    return [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices)) if prices[i - 1] != 0]


def volatility_size_multiplier(price_history: list[float]) -> float:
    """Shrinks a buy when the asset is choppier right now than its own
    recent baseline, and allows a somewhat larger one when it's unusually
    calm. Deliberately self-relative (a short window vs the whole available
    window) rather than anchored to some universal "normal volatility"
    constant -- live tick-to-tick returns and backtest candle-to-candle
    returns sit on completely different scales and can't share one
    reference number, but "quieter/choppier than its own recent self" means
    the same thing on both.
    """
    returns = _returns(price_history)
    if len(returns) < MIN_RETURNS:
        return 1.0

    baseline_vol = statistics.pstdev(returns)
    recent_vol = statistics.pstdev(returns[-SHORT_WINDOW:])
    if baseline_vol <= 0:
        return 1.0
    if recent_vol <= 0:
        return MAX_MULTIPLIER

    ratio = baseline_vol / recent_vol
    return max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, ratio))
