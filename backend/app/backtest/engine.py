from collections import deque

from app.execution.fill_simulator import simulate_fill
from app.strategies.base import StrategyContext
from app.strategies.registry import STRATEGY_BUILDERS
from app.strategies.regime import pick_strategy

REGIME_HISTORY_LENGTH = 30


def _run_hold(symbol: str, candles: list[list], starting_balance_usd: float) -> dict:
    """Baseline: buy once at the first candle and hold to the end, so active
    strategies have something honest to be compared against."""
    first_close = candles[0][4]
    fill_price, qty, fee = simulate_fill(first_close, "buy", 1.0, starting_balance_usd, 0.0)
    cash_usd = starting_balance_usd - fill_price * qty - fee
    equity_curve = [cash_usd + qty * candle[4] for candle in candles]

    return {
        "starting_balance_usd": starting_balance_usd,
        "equity_curve": equity_curve,
        "trades": [{"side": "buy", "qty": qty, "price": fill_price, "fee": fee, "reason": "hold: initial buy"}],
        "win_pnls": [],
        "loss_pnls": [],
    }


def _run_auto(symbol: str, candles: list[list], starting_balance_usd: float) -> dict:
    """Same regime-based strategy switching as a live 'auto' session (see
    session/loop.py): every candle, recent price action decides whether Grid
    or Trend/momentum is in control, with the same hysteresis. All
    strategies stay ticking so their state carries over correctly on a
    switch; only the active one's buys execute, but any strategy's sell
    always goes through so a position never gets stranded."""
    base_asset = symbol.split("/")[0]
    first_close = candles[0][4]
    strategies = {name: builder(symbol, first_close) for name, builder in STRATEGY_BUILDERS.items()}

    cash_usd = starting_balance_usd
    held_qty = 0.0
    avg_cost = 0.0
    price_history: deque[float] = deque(maxlen=REGIME_HISTORY_LENGTH)
    previous_regime = None

    equity_curve = []
    trade_log = []
    win_pnls: list[float] = []
    loss_pnls: list[float] = []

    for candle in candles:
        close = candle[4]
        price_history.append(close)
        active_strategy_name, previous_regime = pick_strategy(list(price_history), previous_regime)

        ctx = StrategyContext(symbol=symbol, price=close, cash_usd=cash_usd, holdings={base_asset: held_qty})

        for strategy_name, strategy in strategies.items():
            for signal in strategy.on_tick(ctx):
                if signal.side == "buy" and strategy_name != active_strategy_name:
                    continue
                fill_price, qty, fee = simulate_fill(close, signal.side, signal.size_fraction, cash_usd, held_qty)
                if qty <= 0:
                    continue

                if signal.side == "buy":
                    cash_usd -= fill_price * qty + fee
                    avg_cost = (avg_cost * held_qty + fill_price * qty) / (held_qty + qty)
                    held_qty += qty
                else:
                    realized_pnl = (fill_price - avg_cost) * qty - fee
                    if realized_pnl > 0:
                        win_pnls.append(realized_pnl)
                    else:
                        loss_pnls.append(realized_pnl)
                    cash_usd += fill_price * qty - fee
                    held_qty -= qty

                trade_log.append(
                    {"side": signal.side, "qty": qty, "price": fill_price, "fee": fee, "reason": signal.reason}
                )

        equity_curve.append(cash_usd + held_qty * close)

    return {
        "starting_balance_usd": starting_balance_usd,
        "equity_curve": equity_curve,
        "trades": trade_log,
        "win_pnls": win_pnls,
        "loss_pnls": loss_pnls,
    }


def run_backtest(strategy_name: str, symbol: str, candles: list[list], starting_balance_usd: float = 10000.0) -> dict:
    """Replays a strategy candle-by-candle over historical OHLCV data using
    the same fill simulation as live paper trading, tracking an average cost
    basis so we can tell a winning trade from a losing one."""

    if strategy_name == "hold":
        return _run_hold(symbol, candles, starting_balance_usd)

    if strategy_name == "auto":
        return _run_auto(symbol, candles, starting_balance_usd)

    builder = STRATEGY_BUILDERS[strategy_name]
    base_asset = symbol.split("/")[0]
    first_close = candles[0][4]
    strategy = builder(symbol, first_close)

    cash_usd = starting_balance_usd
    held_qty = 0.0
    avg_cost = 0.0

    equity_curve = []
    trade_log = []
    win_pnls: list[float] = []
    loss_pnls: list[float] = []

    for candle in candles:
        close = candle[4]
        ctx = StrategyContext(symbol=symbol, price=close, cash_usd=cash_usd, holdings={base_asset: held_qty})
        signals = strategy.on_tick(ctx)

        for signal in signals:
            fill_price, qty, fee = simulate_fill(close, signal.side, signal.size_fraction, cash_usd, held_qty)
            if qty <= 0:
                continue

            if signal.side == "buy":
                cash_usd -= fill_price * qty + fee
                avg_cost = (avg_cost * held_qty + fill_price * qty) / (held_qty + qty)
                held_qty += qty
            else:
                realized_pnl = (fill_price - avg_cost) * qty - fee
                if realized_pnl > 0:
                    win_pnls.append(realized_pnl)
                else:
                    loss_pnls.append(realized_pnl)
                cash_usd += fill_price * qty - fee
                held_qty -= qty

            trade_log.append(
                {"side": signal.side, "qty": qty, "price": fill_price, "fee": fee, "reason": signal.reason}
            )

        equity_curve.append(cash_usd + held_qty * close)

    return {
        "starting_balance_usd": starting_balance_usd,
        "equity_curve": equity_curve,
        "trades": trade_log,
        "win_pnls": win_pnls,
        "loss_pnls": loss_pnls,
    }
