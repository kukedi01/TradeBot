import random

from app.strategies.base import StrategyContext
from app.strategies.trend_momentum import TrendMomentumStrategy


def gentle_uptrend(n=35, seed=7, drift=0.15, noise=0.3):
    rng = random.Random(seed)
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] + drift + rng.uniform(-noise, noise))
    return prices


def run(strategy, prices, volumes=None, holdings_by_tick=None):
    signals = []
    for i, price in enumerate(prices):
        holdings = holdings_by_tick[i] if holdings_by_tick else {}
        volume = volumes[i] if volumes else 10.0
        ctx = StrategyContext(symbol="TEST/EUR", price=price, cash_usd=1000.0, holdings=holdings, volume=volume)
        signals.extend(strategy.on_tick(ctx))
    return signals


class TestPositionDerivedFromHoldings:
    def test_no_buy_signal_ever_fires_while_already_holding(self):
        strategy = TrendMomentumStrategy(symbol="TEST/EUR", min_cross_gap_pct=0.0, volume_confirmation_multiplier=0.0)
        prices = gentle_uptrend()
        holdings = [{"TEST": 1.0}] * len(prices)
        signals = run(strategy, prices, holdings_by_tick=holdings)
        assert all(s.side != "buy" for s in signals)

    def test_no_phantom_sell_retry_when_holdings_are_actually_zero(self):
        # A falling price satisfies the death-cross/band-break exit
        # condition every tick, but with zero real holdings there must be
        # nothing to sell -- this is the exact bug that left ETH/SOL
        # retrying a sell forever in the live session.
        strategy = TrendMomentumStrategy(symbol="TEST/EUR")
        falling = [150.0 - i * 0.5 for i in range(25)]
        signals = run(strategy, falling, holdings_by_tick=[{}] * len(falling))
        assert signals == []

    def test_sell_fires_when_genuinely_holding_and_trend_breaks(self):
        strategy = TrendMomentumStrategy(symbol="TEST/EUR")
        falling = [150.0 - i * 0.5 for i in range(25)]
        signals = run(strategy, falling, holdings_by_tick=[{"TEST": 1.0}] * len(falling))
        assert any(s.side == "sell" for s in signals)


class TestCrossGapHysteresis:
    def test_noisy_flat_market_produces_no_signals_with_default_gap(self):
        rng = random.Random(42)
        prices = [1.245]
        for _ in range(60):
            prices.append(prices[-1] * (1 + rng.uniform(-0.0006, 0.0006)))
        strategy = TrendMomentumStrategy(symbol="TEST/EUR")  # default min_cross_gap_pct=0.15
        signals = run(strategy, prices)
        assert signals == []

    def test_same_noisy_market_whipsaws_without_the_gap_requirement(self):
        rng = random.Random(42)
        prices = [1.245]
        for _ in range(60):
            prices.append(prices[-1] * (1 + rng.uniform(-0.0006, 0.0006)))
        strategy = TrendMomentumStrategy(symbol="TEST/EUR", min_cross_gap_pct=0.0, volume_confirmation_multiplier=0.0)
        signals = run(strategy, prices)
        assert len(signals) > 0


class TestMacdAndVolumeConfirmation:
    def test_buy_blocked_when_volume_is_below_its_own_recent_average(self):
        prices = gentle_uptrend()
        # High volume early (raises the rolling average), then quiet right
        # as the cross would otherwise fire.
        volumes = [80.0] * 15 + [5.0] * (len(prices) - 15)
        strategy = TrendMomentumStrategy(symbol="TEST/EUR", min_cross_gap_pct=0.0)
        signals = run(strategy, prices, volumes=volumes)
        assert all(s.side != "buy" for s in signals)

    def test_buy_confirmed_with_consistent_above_average_volume(self):
        prices = gentle_uptrend()
        strategy = TrendMomentumStrategy(symbol="TEST/EUR", min_cross_gap_pct=0.0)
        signals = run(strategy, prices, volumes=[10.0] * len(prices))
        assert any(s.side == "buy" for s in signals)

    def test_buy_reason_mentions_macd_and_volume(self):
        prices = gentle_uptrend()
        strategy = TrendMomentumStrategy(symbol="TEST/EUR", min_cross_gap_pct=0.0)
        signals = run(strategy, prices, volumes=[10.0] * len(prices))
        buys = [s for s in signals if s.side == "buy"]
        assert buys
        assert "MACD confirmed" in buys[0].reason
        assert "volume" in buys[0].reason
