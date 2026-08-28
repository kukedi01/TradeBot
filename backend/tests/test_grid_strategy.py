from app.strategies.base import StrategyContext
from app.strategies.grid import GridStrategy


def make_grid(**overrides):
    params = dict(symbol="BTC/EUR", lower_bound=95.0, upper_bound=105.0, grid_levels=10, order_size_fraction=0.1)
    params.update(overrides)
    return GridStrategy(**params)


def tick(strategy, price, holdings=None):
    ctx = StrategyContext(symbol="BTC/EUR", price=price, cash_usd=1000.0, holdings=holdings or {})
    return strategy.on_tick(ctx)


class TestBuyAndSell:
    def test_first_tick_only_establishes_baseline_no_signal(self):
        grid = make_grid()
        assert tick(grid, 100.0) == []

    def test_dip_into_a_new_level_fires_a_buy(self):
        grid = make_grid()
        tick(grid, 100.0)
        signals = tick(grid, 98.5)  # one level down
        assert len(signals) == 1
        assert signals[0].side == "buy"

    def test_rise_back_out_of_an_owned_level_fires_a_sell(self):
        grid = make_grid()
        tick(grid, 100.0)
        tick(grid, 98.5)  # buys level 3
        signals = tick(grid, 100.5)  # rises back out
        assert len(signals) == 1
        assert signals[0].side == "sell"

    def test_same_level_produces_no_repeat_signal(self):
        grid = make_grid()
        tick(grid, 100.0)
        tick(grid, 98.5)
        signals = tick(grid, 98.6)  # still within the same level
        assert signals == []


class TestHysteresis:
    def test_tiny_move_within_min_move_pct_is_suppressed(self):
        grid = make_grid(min_move_pct=5.0)  # require a large move to re-trigger
        tick(grid, 100.0)
        tick(grid, 98.5)  # first buy sets last_trade_price to 98.5
        # A further dip into a new level (98.5 -> 96.0 is only ~2.5% away)
        # shouldn't count as "far enough" yet under a 5% hysteresis gate.
        signals = tick(grid, 96.0)
        assert signals == []


class TestOutOfRangeAndRecenter:
    def test_out_of_range_tick_returns_no_signal(self):
        grid = make_grid()
        tick(grid, 100.0)
        assert tick(grid, 200.0) == []

    def test_recenters_after_enough_ticks_out_of_range(self):
        grid = make_grid(recenter_after_ticks_out_of_range=2)
        tick(grid, 100.0)
        tick(grid, 200.0)
        tick(grid, 200.0)
        assert grid.lower_bound < 200.0 < grid.upper_bound
        assert grid.owned_levels == set()


class TestExternalStateCorrections:
    def test_on_external_sell_clears_owned_levels(self):
        grid = make_grid()
        tick(grid, 100.0)
        tick(grid, 98.5)
        assert grid.owned_levels != set()
        grid.on_external_sell()
        assert grid.owned_levels == set()

    def test_on_signal_not_filled_rolls_back_a_failed_buy(self):
        grid = make_grid()
        tick(grid, 100.0)
        tick(grid, 98.5)  # buy signal for a level, speculatively marked owned
        owned_before_rollback = set(grid.owned_levels)
        assert owned_before_rollback != set()

        grid.on_signal_not_filled()
        assert grid.owned_levels == set()

        # The same dip should be retryable now that it isn't falsely owned.
        tick(grid, 100.5)  # bounce up first
        signals = tick(grid, 98.5)  # dip back to the same level
        assert any(s.side == "buy" for s in signals)

    def test_on_signal_not_filled_rolls_back_a_failed_sell(self):
        grid = make_grid()
        tick(grid, 100.0)
        tick(grid, 98.5)  # genuine buy, level owned
        tick(grid, 100.5)  # sell signal fires, level speculatively un-owned
        assert 3 not in grid.owned_levels

        grid.on_signal_not_filled()
        assert 3 in grid.owned_levels

    def test_on_signal_not_filled_without_a_pending_signal_is_a_no_op(self):
        grid = make_grid()
        tick(grid, 100.0)
        grid.on_signal_not_filled()  # nothing pending -- must not raise
        assert grid.owned_levels == set()
