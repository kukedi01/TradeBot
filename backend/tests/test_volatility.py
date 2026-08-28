from app.risk.volatility import (
    MAX_MULTIPLIER,
    MIN_MULTIPLIER,
    MIN_RETURNS,
    volatility_size_multiplier,
)


def test_insufficient_history_leaves_size_untouched():
    multiplier = volatility_size_multiplier([100.0, 101.0, 102.0])
    assert multiplier == 1.0


def test_choppy_recent_window_shrinks_toward_the_floor():
    calm = [100.0 + 0.01 * i for i in range(25)]
    choppy_tail = [calm[-1]]
    for i in range(6):
        choppy_tail.append(choppy_tail[-1] * (1.03 if i % 2 == 0 else 0.97))
    prices = calm + choppy_tail[1:]
    assert len(prices) - 1 >= MIN_RETURNS

    multiplier = volatility_size_multiplier(prices)
    assert multiplier < 1.0
    assert multiplier >= MIN_MULTIPLIER


def test_calm_recent_window_after_a_choppy_baseline_sizes_up():
    choppy = [100.0]
    for i in range(20):
        choppy.append(choppy[-1] * (1.02 if i % 2 == 0 else 0.98))
    calm_tail = [choppy[-1] + 0.001 * i for i in range(8)]
    prices = choppy + calm_tail

    multiplier = volatility_size_multiplier(prices)
    assert multiplier == MAX_MULTIPLIER


def test_multiplier_is_always_within_configured_bounds():
    import random

    random.seed(3)
    prices = [100.0]
    for _ in range(40):
        prices.append(prices[-1] * (1 + random.uniform(-0.05, 0.05)))

    multiplier = volatility_size_multiplier(prices)
    assert MIN_MULTIPLIER <= multiplier <= MAX_MULTIPLIER
