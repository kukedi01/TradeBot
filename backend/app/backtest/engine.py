from collections import deque

from app.constants import HANDOFF_MIN_PROFIT_MARGIN_PCT
from app.execution.fill_simulator import simulate_fill
from app.risk.correlation import compute_correlation_matrix_from_returns, correlation_size_multiplier, returns_from_closes
from app.risk.guardrails import check_drawdown_limit, check_position_stop_loss, concentration_size_multiplier
from app.risk.volatility import volatility_size_multiplier
from app.strategies.base import StrategyContext
from app.strategies.registry import STRATEGY_BUILDERS
from app.strategies.regime import pick_strategy

REGIME_HISTORY_LENGTH = 30


def _resolve_size_override(size_fraction_override: float | dict[str, float] | None, strategy_name: str) -> float | None:
    """A backtest can be run either with each strategy's own hand-picked
    default size (pass None -- the historical behavior) or with the
    Kelly-derived sizes a live session actually hands its strategies (pass a
    float, or a per-strategy dict, from risk/position_sizing.py's
    live_size_overrides()). The difference is not cosmetic: live grid runs at
    the 0.8 Kelly cap while its own default is 0.1, an 8x gap that made every
    "auto" backtest look far less invested -- and therefore far less
    profitable in a rising market -- than the bot really is. Computing the
    Kelly value here instead of taking it as a parameter isn't possible:
    risk/position_sizing.py imports this module, so importing it back would
    be a circular import (and would recurse, since Kelly is itself a
    backtest)."""
    if size_fraction_override is None:
        return None
    if isinstance(size_fraction_override, dict):
        return size_fraction_override.get(strategy_name)
    return size_fraction_override


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


def _run_auto(
    symbol: str,
    candles: list[list],
    starting_balance_usd: float,
    size_fraction_override: float | dict[str, float] | None = None,
) -> dict:
    """Same regime-based strategy switching as a live 'auto' session (see
    session/loop.py): every candle, recent price action decides whether Grid
    or Trend/momentum is in control, with the same hysteresis. All
    strategies stay ticking so their state carries over correctly on a
    switch; only the active one's buys execute. A sell executes from the
    position's actual owner (whichever strategy's buy created the currently
    held quantity) or from the currently active strategy (so a regime flip
    can still hand off the exit) -- and a handoff sell (active strategy
    closing a position it didn't open) additionally must clear the
    *original* owner's cost basis by HANDOFF_MIN_PROFIT_MARGIN_PCT, exactly
    like session/loop.py's run_tick. Before this was added, this backtest
    was silently testing a more permissive "any strategy's sell always goes
    through" rule that live auto sessions haven't actually used since --
    it let trend_momentum whipsaw out grid's dip-buys within hours at a
    negligible or negative margin on every regime flip, which is most of why
    a 29-day BTC 'auto' backtest showed only +1.4% while price itself rose
    +22.6%: not a real strategy limitation, a stale backtest/live mismatch."""
    base_asset = symbol.split("/")[0]
    first_close = candles[0][4]
    strategies = {
        name: builder(symbol, first_close, size_fraction_override=_resolve_size_override(size_fraction_override, name))
        for name, builder in STRATEGY_BUILDERS.items()
    }

    cash_usd = starting_balance_usd
    held_qty = 0.0
    avg_cost = 0.0
    position_owner: str | None = None
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

        ctx = StrategyContext(
            symbol=symbol,
            price=close,
            cash_usd=cash_usd,
            holdings={base_asset: held_qty},
            volume=candle[5],
            cost_basis=avg_cost if held_qty > 0 else 0.0,
        )

        for strategy_name, strategy in strategies.items():
            for signal in strategy.on_tick(ctx):
                if signal.side == "buy" and strategy_name != active_strategy_name:
                    strategy.on_signal_not_filled()
                    continue
                if (
                    signal.side == "sell"
                    and position_owner is not None
                    and strategy_name != position_owner
                    and strategy_name != active_strategy_name
                ):
                    strategy.on_signal_not_filled()
                    continue
                if (
                    signal.side == "sell"
                    and position_owner is not None
                    and strategy_name != position_owner
                    and avg_cost > 0
                    and close < avg_cost * (1 + HANDOFF_MIN_PROFIT_MARGIN_PCT / 100)
                ):
                    strategy.on_signal_not_filled()
                    continue
                size_fraction = signal.size_fraction
                if signal.side == "buy":
                    size_fraction *= volatility_size_multiplier(list(price_history))
                fill_price, qty, fee = simulate_fill(close, signal.side, size_fraction, cash_usd, held_qty)
                if qty <= 0:
                    strategy.on_signal_not_filled()
                    continue

                if signal.side == "buy":
                    cash_usd -= fill_price * qty + fee
                    avg_cost = (avg_cost * held_qty + fill_price * qty) / (held_qty + qty)
                    held_qty += qty
                    position_owner = strategy_name
                else:
                    realized_pnl = (fill_price - avg_cost) * qty - fee
                    if realized_pnl > 0:
                        win_pnls.append(realized_pnl)
                    else:
                        loss_pnls.append(realized_pnl)
                    cash_usd += fill_price * qty - fee
                    held_qty -= qty
                    if held_qty <= 1e-9:
                        position_owner = None

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


def run_backtest(
    strategy_name: str,
    symbol: str,
    candles: list[list],
    starting_balance_usd: float = 10000.0,
    size_fraction_override: float | dict[str, float] | None = None,
) -> dict:
    """Replays a strategy candle-by-candle over historical OHLCV data using
    the same fill simulation as live paper trading, tracking an average cost
    basis so we can tell a winning trade from a losing one.

    size_fraction_override defaults to None (each strategy's own default
    size), which is what Kelly sizing itself must use to avoid recursing --
    see _resolve_size_override for why passing live-equivalent sizes matters
    for every other kind of comparison."""

    if strategy_name == "hold":
        return _run_hold(symbol, candles, starting_balance_usd)

    if strategy_name == "auto":
        return _run_auto(symbol, candles, starting_balance_usd, size_fraction_override)

    builder = STRATEGY_BUILDERS[strategy_name]
    base_asset = symbol.split("/")[0]
    first_close = candles[0][4]
    strategy = builder(symbol, first_close, size_fraction_override=_resolve_size_override(size_fraction_override, strategy_name))

    cash_usd = starting_balance_usd
    held_qty = 0.0
    avg_cost = 0.0
    price_history: deque[float] = deque(maxlen=REGIME_HISTORY_LENGTH)

    equity_curve = []
    trade_log = []
    win_pnls: list[float] = []
    loss_pnls: list[float] = []

    for candle in candles:
        close = candle[4]
        price_history.append(close)
        ctx = StrategyContext(
            symbol=symbol,
            price=close,
            cash_usd=cash_usd,
            holdings={base_asset: held_qty},
            volume=candle[5],
            cost_basis=avg_cost if held_qty > 0 else 0.0,
        )
        signals = strategy.on_tick(ctx)

        for signal in signals:
            size_fraction = signal.size_fraction
            if signal.side == "buy":
                size_fraction *= volatility_size_multiplier(list(price_history))
            fill_price, qty, fee = simulate_fill(close, signal.side, size_fraction, cash_usd, held_qty)
            if qty <= 0:
                strategy.on_signal_not_filled()
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


def _align_candles(candles_by_symbol: dict[str, list[list]]) -> dict[str, list[list]]:
    """Keeps only the timestamps every symbol has a candle for, so "step N"
    means the same moment across all coins. Coins can otherwise differ
    slightly in history length/start even at the same timeframe (e.g. a
    later Kraken listing date)."""
    symbols = list(candles_by_symbol.keys())
    common_timestamps = {candle[0] for candle in candles_by_symbol[symbols[0]]}
    for symbol in symbols[1:]:
        common_timestamps &= {candle[0] for candle in candles_by_symbol[symbol]}
    return {
        symbol: sorted((c for c in candles_by_symbol[symbol] if c[0] in common_timestamps), key=lambda c: c[0])
        for symbol in symbols
    }


def _multi_coin_hold_equity(aligned_candles: dict[str, list[list]], starting_balance_usd: float) -> list[float]:
    """Same baseline as _run_hold, spread evenly across every coin instead
    of one -- buy once at the start, never touch it again."""
    symbols = list(aligned_candles.keys())
    share = starting_balance_usd / len(symbols)
    qty = {}
    for symbol in symbols:
        first_close = aligned_candles[symbol][0][4]
        fill_price, q, _fee = simulate_fill(first_close, "buy", 1.0, share, 0.0)
        qty[symbol] = q

    return [
        sum(qty[symbol] * aligned_candles[symbol][step][4] for symbol in symbols)
        for step in range(len(aligned_candles[symbols[0]]))
    ]


def run_multi_coin_backtest(
    strategy_mode: str,
    candles_by_symbol: dict[str, list[list]],
    starting_balance_usd: float = 10000.0,
    max_drawdown_pct: float | None = None,
    size_fraction_override: float | dict[str, float] | None = None,
) -> dict:
    """Mirrors session/loop.py's run_tick as closely as a backtest can: all
    tradable coins replayed in lockstep against one shared cash pool, with
    the same correlation-based and concentration-cap buy sizing and the
    same position-level stop-loss -- none of which run_backtest() above can
    show, since it only ever simulates one coin in isolation and has no
    notion of "what else this session is holding."

    strategy_mode is either "auto" (regime-based per-coin switching, like a
    live auto session) or one of STRATEGY_BUILDERS's keys (that one
    strategy run independently on every coin, like a live fixed-strategy
    session).

    The correlation matrix is computed ONCE, from the full backtest
    window's own daily returns -- not refetched live and not rolled
    forward candle by candle. A live session recomputes it hourly against
    whatever the last 90 days looked like *at that moment*; a single
    snapshot of "how these coins moved during this backtest period" is the
    same kind of simplification as the train/test validator's split (see
    validation.py) -- close enough to size trades realistically, not a
    rolling walk-forward reproduction of the live cache.

    News sentiment is deliberately not simulated here -- there's no
    historical headline archive to replay, and it's the one live input
    that's genuinely irreplaceable in a backtest.
    """
    is_auto = strategy_mode == "auto"
    aligned = _align_candles(candles_by_symbol)
    symbols = list(aligned.keys())
    step_count = len(aligned[symbols[0]])

    returns_by_symbol = {symbol: returns_from_closes([c[4] for c in aligned[symbol]]) for symbol in symbols}
    correlation_matrix = compute_correlation_matrix_from_returns(returns_by_symbol)

    cash_usd = starting_balance_usd
    holdings: dict[str, float] = {}
    cost_basis: dict[str, float] = {}
    strategies: dict[tuple[str, str], object] = {}
    price_histories: dict[str, deque[float]] = {symbol: deque(maxlen=REGIME_HISTORY_LENGTH) for symbol in symbols}
    previous_regime: dict[str, str | None] = {symbol: None for symbol in symbols}

    equity_curve: list[float] = []
    trade_log: list[dict] = []
    win_pnls: list[float] = []
    loss_pnls: list[float] = []
    stopped = False

    def get_strategy(symbol: str, name: str, first_price: float):
        key = (symbol, name)
        if key not in strategies:
            strategies[key] = STRATEGY_BUILDERS[name](
                symbol, first_price, size_fraction_override=_resolve_size_override(size_fraction_override, name)
            )
        return strategies[key]

    for step in range(step_count):
        prices = {symbol: aligned[symbol][step][4] for symbol in symbols}
        volumes = {symbol: aligned[symbol][step][5] for symbol in symbols}

        if not stopped:
            for symbol in symbols:
                base_asset = symbol.split("/")[0]
                price = prices[symbol]

                if is_auto:
                    price_histories[symbol].append(price)
                    active_strategy_name, previous_regime[symbol] = pick_strategy(
                        list(price_histories[symbol]), previous_regime[symbol]
                    )
                    candidate_names = list(STRATEGY_BUILDERS.keys())
                else:
                    active_strategy_name = strategy_mode
                    candidate_names = [strategy_mode]

                # Position-level stop-loss, checked before this symbol's
                # strategies get a turn this step -- same order as
                # session/loop.py's run_tick.
                held_qty = holdings.get(base_asset, 0)
                if held_qty > 0:
                    stop_loss = check_position_stop_loss(price, cost_basis.get(base_asset, 0.0))
                    if stop_loss.triggered:
                        fill_price, qty, fee = simulate_fill(price, "sell", 1.0, cash_usd, held_qty)
                        if qty > 0:
                            realized_pnl = (fill_price - cost_basis.get(base_asset, 0.0)) * qty - fee
                            (win_pnls if realized_pnl > 0 else loss_pnls).append(realized_pnl)
                            cash_usd += fill_price * qty - fee
                            holdings[base_asset] = held_qty - qty
                            trade_log.append(
                                {
                                    "side": "sell",
                                    "symbol": symbol,
                                    "qty": qty,
                                    "price": fill_price,
                                    "fee": fee,
                                    "reason": f"risk: stop-loss triggered ({stop_loss.loss_pct:.1f}% below entry)",
                                }
                            )
                            for name in candidate_names:
                                key = (symbol, name)
                                if key in strategies:
                                    strategies[key].on_external_sell()

                ctx = StrategyContext(
                    symbol=symbol,
                    price=price,
                    cash_usd=cash_usd,
                    holdings=dict(holdings),
                    volume=volumes[symbol],
                    cost_basis=cost_basis.get(base_asset, 0.0),
                )

                for name in candidate_names:
                    strategy = get_strategy(symbol, name, price)
                    for signal in strategy.on_tick(ctx):
                        if signal.side == "buy" and name != active_strategy_name:
                            strategy.on_signal_not_filled()
                            continue
                        size_fraction = signal.size_fraction
                        if signal.side == "buy":
                            size_fraction *= correlation_size_multiplier(symbol, holdings, prices, correlation_matrix)
                            size_fraction *= concentration_size_multiplier(
                                symbol, size_fraction, cash_usd, holdings, prices
                            )
                            window_start = max(0, step + 1 - REGIME_HISTORY_LENGTH)
                            recent_closes = [c[4] for c in aligned[symbol][window_start : step + 1]]
                            size_fraction *= volatility_size_multiplier(recent_closes)
                        held_qty = holdings.get(base_asset, 0)
                        fill_price, qty, fee = simulate_fill(price, signal.side, size_fraction, cash_usd, held_qty)
                        if qty <= 0:
                            strategy.on_signal_not_filled()
                            continue
                        if signal.side == "buy":
                            cash_usd -= fill_price * qty + fee
                            avg_cost = cost_basis.get(base_asset, 0.0)
                            cost_basis[base_asset] = (avg_cost * held_qty + fill_price * qty) / (held_qty + qty)
                            holdings[base_asset] = held_qty + qty
                        else:
                            realized_pnl = (fill_price - cost_basis.get(base_asset, 0.0)) * qty - fee
                            (win_pnls if realized_pnl > 0 else loss_pnls).append(realized_pnl)
                            cash_usd += fill_price * qty - fee
                            holdings[base_asset] = held_qty - qty
                        trade_log.append(
                            {
                                "side": signal.side,
                                "symbol": symbol,
                                "qty": qty,
                                "price": fill_price,
                                "fee": fee,
                                "reason": signal.reason,
                            }
                        )

        total_value = cash_usd + sum(holdings.get(sym.split("/")[0], 0) * prices[sym] for sym in symbols)
        equity_curve.append(total_value)

        if not stopped:
            # Same guardrail as a live session: once the portfolio has
            # fallen too far below its own peak, stop trading for the rest
            # of the backtest (the equity curve keeps marking frozen
            # holdings to market, same as a real risk_stopped session that
            # nobody has manually closed).
            risk_check = check_drawdown_limit(total_value, equity_curve[:-1], max_drawdown_pct)
            if risk_check.breached:
                stopped = True

    return {
        "starting_balance_usd": starting_balance_usd,
        "equity_curve": equity_curve,
        "hodl_equity_curve": _multi_coin_hold_equity(aligned, starting_balance_usd),
        "trades": trade_log,
        "win_pnls": win_pnls,
        "loss_pnls": loss_pnls,
        "stopped_early": stopped,
    }
