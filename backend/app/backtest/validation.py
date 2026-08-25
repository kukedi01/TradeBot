from app.backtest.engine import run_backtest
from app.backtest.metrics import compute_metrics


def run_train_test_split(
    strategy_name: str,
    symbol: str,
    candles: list[list],
    starting_balance_usd: float = 10000.0,
    split_ratio: float = 0.7,
) -> dict:
    """Splits the candle history into an earlier and a later slice and backtests
    the strategy on each separately. Since our strategies use fixed, hand-picked
    parameters (nothing was fitted to this data), this checks something more
    basic than classic overfitting protection: whether the strategy's edge
    holds up consistently across different sub-periods of the sample, or only
    "worked" on one slice by chance.
    """
    split_idx = int(len(candles) * split_ratio)
    train_candles = candles[:split_idx]
    test_candles = candles[split_idx:]

    train_metrics = compute_metrics(run_backtest(strategy_name, symbol, train_candles, starting_balance_usd))
    test_metrics = compute_metrics(run_backtest(strategy_name, symbol, test_candles, starting_balance_usd))

    return {"train": train_metrics, "test": test_metrics}
