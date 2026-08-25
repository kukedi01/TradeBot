from typing import Literal

Regime = Literal["trending", "ranging"]

# Kaufman's Efficiency Ratio: net price move over the window divided by the
# total distance the price actually travelled tick-to-tick. Close to 1 means
# the price moved in mostly one direction (trending); close to 0 means it
# wandered back and forth without going anywhere (ranging/sideways).
MIN_HISTORY = 20

# Hysteresis band, same idea as the grid strategy's min_move_pct: a single
# shared threshold would let a ratio hovering right at the boundary flip the
# active strategy back and forth every tick on pure noise. Switching TO
# trending needs a clearly stronger signal (0.35) than switching back OUT of
# it (0.25) -- in between, whichever regime was already active stays active.
ENTER_TREND_THRESHOLD = 0.35
EXIT_TREND_THRESHOLD = 0.25

# Which strategy handles each regime. Grid trading profits from price
# oscillating inside a band, so it fits ranging markets; trend/momentum only
# enters when there's a clear direction, so it fits trending markets.
REGIME_STRATEGY: dict[Regime, str] = {
    "trending": "trend_momentum",
    "ranging": "grid",
}

# Used before there's enough price history to judge the regime yet.
FALLBACK_STRATEGY = "grid"


def detect_regime(prices: list[float], previous_regime: Regime | None = None) -> Regime | None:
    if len(prices) < MIN_HISTORY:
        return None

    net_move = abs(prices[-1] - prices[0])
    path_length = sum(abs(prices[i] - prices[i - 1]) for i in range(1, len(prices)))
    efficiency = net_move / path_length if path_length > 0 else 0.0

    threshold = EXIT_TREND_THRESHOLD if previous_regime == "trending" else ENTER_TREND_THRESHOLD
    return "trending" if efficiency >= threshold else "ranging"


def pick_strategy(prices: list[float], previous_regime: Regime | None = None) -> tuple[str, Regime | None]:
    regime = detect_regime(prices, previous_regime)
    strategy_name = REGIME_STRATEGY[regime] if regime is not None else FALLBACK_STRATEGY
    return strategy_name, regime
