import random

from app.backtest.engine import run_backtest, run_multi_coin_backtest


def make_candles(n=80, start_price=100.0, seed=1, timeframe_ms=3_600_000):
    rng = random.Random(seed)
    candles = []
    price = start_price
    timestamp = 0
    for _ in range(n):
        drift = rng.uniform(-0.5, 0.6)
        price = max(price + drift, 1.0)
        high = price + rng.uniform(0, 1.0)
        low = price - rng.uniform(0, 1.0)
        volume = rng.uniform(50, 500)
        candles.append([timestamp, price, high, low, price, volume])
        timestamp += timeframe_ms
    return candles


class TestRunBacktestSmoke:
    def test_hold_baseline_never_trades_after_the_initial_buy(self):
        candles = make_candles()
        result = run_backtest("hold", "TEST/EUR", candles)
        assert len(result["trades"]) == 1
        assert len(result["equity_curve"]) == len(candles)

    def test_fixed_strategy_produces_a_well_formed_result(self):
        candles = make_candles()
        result = run_backtest("grid", "TEST/EUR", candles)
        assert set(result.keys()) >= {"starting_balance_usd", "equity_curve", "trades", "win_pnls", "loss_pnls"}
        assert len(result["equity_curve"]) == len(candles)

    def test_auto_mode_produces_a_well_formed_result(self):
        candles = make_candles()
        result = run_backtest("auto", "TEST/EUR", candles)
        assert len(result["equity_curve"]) == len(candles)


class TestMultiCoinBacktestSmoke:
    def test_runs_across_all_symbols_without_crashing(self):
        candles_by_symbol = {
            "BTC/EUR": make_candles(seed=1, start_price=60000.0),
            "ETH/EUR": make_candles(seed=2, start_price=2000.0),
            "SOL/EUR": make_candles(seed=3, start_price=100.0),
            "XRP/EUR": make_candles(seed=4, start_price=1.0),
        }
        result = run_multi_coin_backtest("auto", candles_by_symbol, starting_balance_usd=10000.0, max_drawdown_pct=20.0)
        assert len(result["equity_curve"]) == len(result["hodl_equity_curve"])
        assert result["equity_curve"][0] <= 10000.0 + 1e-6
        assert isinstance(result["stopped_early"], bool)

    def test_tight_drawdown_cap_stops_the_backtest_early(self):
        candles_by_symbol = {
            "BTC/EUR": make_candles(seed=5, start_price=60000.0),
            "ETH/EUR": make_candles(seed=6, start_price=2000.0),
            "SOL/EUR": make_candles(seed=7, start_price=100.0),
            "XRP/EUR": make_candles(seed=8, start_price=1.0),
        }
        result = run_multi_coin_backtest("auto", candles_by_symbol, starting_balance_usd=10000.0, max_drawdown_pct=0.01)
        assert result["stopped_early"] is True

    def test_mismatched_candle_timestamps_are_aligned_not_crashed_on(self):
        btc = make_candles(seed=9, start_price=60000.0)
        eth = make_candles(seed=10, start_price=2000.0)[2:]  # starts later than BTC
        result = run_multi_coin_backtest(
            "grid",
            {"BTC/EUR": btc, "ETH/EUR": eth, "SOL/EUR": btc, "XRP/EUR": btc},
            starting_balance_usd=1000.0,
        )
        assert len(result["equity_curve"]) == len(eth)
