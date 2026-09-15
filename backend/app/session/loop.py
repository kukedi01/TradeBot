import threading
import time
from collections import deque
from datetime import datetime

from sqlalchemy.orm import Session as DbSession

from app.constants import HANDOFF_MIN_PROFIT_MARGIN_PCT, TRADABLE_SYMBOLS
from app.db.models import Portfolio, PortfolioSnapshot, TradingSession
from app.execution.paper_executor import PaperExecutor
from app.market_data.kraken_client import get_ticker_price, get_ticker_volume
from app.news.reactor import get_sentiment_state
from app.notifications import send_desktop_notification
from app.risk.correlation import correlation_size_multiplier, get_correlation_matrix
from app.risk.guardrails import check_drawdown_limit, check_position_stop_loss, concentration_size_multiplier
from app.risk.position_sizing import compute_kelly_size_for_strategy
from app.risk.volatility import volatility_size_multiplier
from app.session.state_store import POSITION_OWNER_KEY, REGIME_HISTORY_KEY, TREND_4H_HISTORY_KEY, load_state, save_state
from app.strategies.base import Strategy, StrategyContext
from app.strategies.indicators import macd_series, rsi_series, sma
from app.strategies.registry import STRATEGY_BUILDERS
from app.strategies.regime import REGIME_STRATEGY, pick_strategy

# A session with this strategy_name doesn't pick one strategy up front --
# every tick, each coin's recent price action decides which strategy handles
# it (see strategies/regime.py).
AUTO_STRATEGY = "auto"

# Strategies allowed to open positions regardless of which one the regime
# classifier currently favours, because each already refuses its own weak
# setups: trend_momentum needs a confirmed cross (min_cross_gap_pct), MACD
# agreement, above-average volume and 4h trend agreement; grid needs a real
# level crossing past min_move_pct hysteresis and will only exit above its
# blended cost basis.
#
# The regime gate used to apply to grid, and measurement showed it was doing
# active harm. Over a 29-day window the label read "trending" 27-38% of the
# time, and in those stretches grid's buys were blocked -- 36 blocked against
# 13 executed on SOL, 30 against 7 on XRP -- while trend_momentum, the
# strategy the gate handed control to, executed 0-1 buys in the entire
# period (its Kelly size is 0.08-0.24 on three of the four coins, since it
# has no proven edge there). The result was a bot that simply sat idle for
# roughly a third of every session: the strategy that would have traded was
# locked out, and the one holding the keys never acted. Removing the gate
# roughly doubled backtested "auto" returns (+2.7% -> +5.3% averaged over
# both market types and all four coins, better in 5 of 8 cases, notably SOL
# +2.3% -> +14.0%). The regime label still selects which strategy is
# reported as active and still governs handoff sells; it just no longer
# decides who is allowed to trade at all.
REGIME_SELF_GATING_STRATEGIES = {"grid", "trend_momentum"}

REGIME_HISTORY_LENGTH = 30
# How many ticks the coin charts (price/volume/RSI/MACD) show -- deliberately
# decoupled from REGIME_HISTORY_LENGTH, which is what the strategies
# themselves actually see for regime detection. The charts exist for a human
# to look at, so they can show more history than the trading logic uses
# without changing any trading behavior. ~30s/tick, so 240 is ~2 hours.
CHART_HISTORY_LENGTH = 240

# How many recent decision-log entries to keep per session -- a rolling
# diagnostic feed (see _log_decision), not durable state, so this resets on
# a backend restart same as _strategy_instances below. Sized generously
# (roughly a full night's worth of 30s ticks across 4 coins x up to 3
# candidate strategies) rather than the minimum needed for a quick check,
# so an overnight unattended run doesn't quietly roll off its early hours
# before anyone's looked at it.
DECISION_LOG_LENGTH = 5000

# One strategy instance per (session, symbol, strategy). In auto mode all
# three strategies for a symbol are kept ticking every cycle so their
# internal state (grid levels, moving averages, ...) stays warm even while
# inactive -- only the regime-selected one's signals actually get executed.
_strategy_instances: dict[tuple[int, str, str], Strategy] = {}
_price_histories: dict[tuple[int, str], deque[float]] = {}
_regime_state: dict[tuple[int, str], dict] = {}
# Every signal a strategy produced this session and what happened to it --
# executed, or blocked/shrunk and why. The trade table only shows what
# *did* happen; this is what lets the frontend show why a strategy that
# looked "active" still didn't trade.
_decision_log: dict[int, deque[dict]] = {}
# Same short rolling window as _price_histories, but kept for every session
# regardless of auto/fixed mode (that one's only populated in auto mode,
# for regime detection) -- purely for charting, so it's independent of
# whatever the trading logic itself needs.
_chart_histories: dict[tuple[int, str], deque[dict]] = {}
# Kraken's ticker only exposes a rolling 24h volume total, which barely
# moves tick to tick -- charting that raw level over a ~30-tick/15-minute
# window would look almost perfectly flat. The delta between two
# consecutive readings approximates how much actually traded in between,
# which is what "volume" is supposed to show. Keyed separately (not just
# read off the last chart-history entry) so it also works on the very
# first tick after a restart, when there's no history yet to diff against.
_last_raw_volume: dict[tuple[int, str], float] = {}
# Which strategy currently owns the open position on a symbol, set on a buy
# fill and cleared once the position is fully closed. Without this, any
# non-active strategy still ticking in the background (e.g. trend_momentum
# reading grid's freshly-bought holdings as "my position") could sell it out
# the moment its own unrelated exit condition fired -- closing a grid dip-buy
# for a small loss within minutes, before grid's own exit ever got a chance.
# Unknown (None) is treated permissively (sell allowed) so a position that
# predates this feature, or survives a backend restart, doesn't get stranded.
_position_owners: dict[tuple[int, str], str] = {}


def _load_position_owner_if_needed(db: DbSession, session_id: int, symbol: str) -> None:
    key = (session_id, symbol)
    if key in _position_owners:
        return
    saved = load_state(db, session_id, symbol, POSITION_OWNER_KEY)
    if saved and saved.get("owner"):
        _position_owners[key] = saved["owner"]


def _set_position_owner(db: DbSession, session_id: int, symbol: str, strategy_name: str) -> None:
    _position_owners[(session_id, symbol)] = strategy_name
    save_state(db, session_id, symbol, POSITION_OWNER_KEY, {"owner": strategy_name})


def _clear_position_owner(db: DbSession, session_id: int, symbol: str) -> None:
    _position_owners.pop((session_id, symbol), None)
    save_state(db, session_id, symbol, POSITION_OWNER_KEY, {"owner": None})


# The APScheduler job never overlaps itself (max_instances=1 skips a cycle
# rather than running two at once -- see scheduler.py), but a manual
# POST /session/{id}/tick can still land while the scheduler's own tick for
# that same session is mid-flight. Two concurrent run_tick() calls for the
# same session would each build their own strategy instances, race on the
# same Portfolio row, and clobber each other's saved state -- exactly the
# kind of corruption that left phantom grid owned_levels behind. One lock
# per session, non-blocking: a tick that can't get in skips rather than waits.
_tick_locks: dict[int, threading.Lock] = {}


def _log_decision(session_id: int, entry: dict) -> None:
    if session_id not in _decision_log:
        _decision_log[session_id] = deque(maxlen=DECISION_LOG_LENGTH)
    _decision_log[session_id].appendleft({"timestamp": datetime.utcnow().isoformat(), **entry})


def get_decision_log(session_id: int) -> list[dict]:
    return list(_decision_log.get(session_id, []))


def _get_strategy(db: DbSession, session_id: int, symbol: str, strategy_name: str) -> Strategy:
    key = (session_id, symbol, strategy_name)
    if key not in _strategy_instances:
        price = get_ticker_price(symbol)
        builder = STRATEGY_BUILDERS[strategy_name]
        # Size live orders off the strategy's own backtested Kelly fraction
        # rather than its fixed default -- a strategy without a proven edge
        # trades small or not at all instead of betting blind. If Kraken's
        # historical data endpoint is unavailable (e.g. rate limited), fall
        # back to the strategy's own default rather than failing the tick.
        try:
            kelly_size = compute_kelly_size_for_strategy(strategy_name, symbol)
        except Exception:
            kelly_size = None
        strategy = builder(symbol, price, size_fraction_override=kelly_size)

        # A process restart wipes this in-memory cache, but not the DB --
        # restore whatever this strategy last knew about this coin so it
        # doesn't start over from scratch.
        saved_state = load_state(db, session_id, symbol, strategy_name)
        if saved_state is not None:
            strategy.load_state(saved_state)

        _strategy_instances[key] = strategy
    return _strategy_instances[key]


def get_regime_state(session_id: int) -> list[dict]:
    return [
        {"symbol": symbol, **_regime_state.get((session_id, symbol), {"regime": None, "active_strategy": None})}
        for symbol in TRADABLE_SYMBOLS
    ]


def _volume_delta(session_id: int, symbol: str, raw_volume_24h: float) -> float:
    key = (session_id, symbol)
    previous = _last_raw_volume.get(key)
    # Kraken's 24h counter resets/jumps occasionally (e.g. crossing a UTC
    # day boundary) -- a negative delta there isn't a real volume of zero
    # trades, it's just the counter rolling over, so floor at 0 either way.
    delta = max(raw_volume_24h - previous, 0.0) if previous is not None else 0.0
    _last_raw_volume[key] = raw_volume_24h
    return delta


def _record_chart_tick(session_id: int, symbol: str, price: float, volume_delta: float) -> None:
    key = (session_id, symbol)
    if key not in _chart_histories:
        _chart_histories[key] = deque(maxlen=CHART_HISTORY_LENGTH)
    _chart_histories[key].append(
        {"timestamp": datetime.utcnow().isoformat(), "price": price, "volume": volume_delta}
    )


def _recent_prices(session_id: int, symbol: str) -> list[float]:
    return [t["price"] for t in _chart_histories.get((session_id, symbol), [])]


# trend_momentum's moving-average periods (fast=5, slow=20) were backtested
# against daily candles (a 150-day backtest hits Kraken's ~700-candle cap at
# finer granularity, so pick_timeframe falls back to "1d"). Feeding it raw
# 30s ticks instead made "5/20" mean 2.5/10 *minutes*, not days -- the
# strategy was catching tick noise, not real trend, and round-tripping in
# 5-10 minutes for a move too small to clear its own ~0.62% round-trip fee
# and slippage cost. Aggregating live ticks into hourly candles and only
# feeding trend_momentum a completed candle gives it a genuine multi-hour
# trend concept again, matching what its parameters were actually validated
# against in spirit (a real backtest is still daily; hourly is the practical
# middle ground for a paper-trading session meant to be watched over hours,
# not weeks).
CANDLE_INTERVAL_SECONDS = 3600
_candle_buckets: dict[tuple[int, str], dict] = {}

# A separate, coarser trend filter on top of the hourly golden cross above:
# only let trend_momentum actually buy when the 4-hour timeframe is *also*
# in an uptrend (its own fast/slow SMA agreeing), not just the 1h one. A
# 29-day backtest comparing 1h-only vs. 1h+4h-agreement showed higher return,
# higher win rate, and fewer/lower-quality trades on all 4 tradable coins --
# the 4h view catches cases where an hourly cross fires against the larger
# trend, which is disproportionately the losing half of trend_momentum's
# trades. Applied as an external gate on the buy signal (like the regime/
# ownership/sentiment checks in run_tick below), not inside the strategy
# class itself, so the strategy's own confirmed-cross logic stays unchanged
# and this filter can be tuned or dropped independently.
CANDLE_4H_INTERVAL_SECONDS = 4 * 3600
TREND_4H_FAST_PERIOD = 5
TREND_4H_SLOW_PERIOD = 20
TREND_4H_HISTORY_LENGTH = 30
_candle_4h_buckets: dict[tuple[int, str], dict] = {}
_trend_4h_history: dict[tuple[int, str], deque[float]] = {}
_trend_4h_uptrend: dict[tuple[int, str], bool] = {}


def _update_candle(session_id: int, symbol: str, price: float, volume: float, now: datetime) -> dict | None:
    """Feeds one raw tick into the current hourly OHLCV bucket for this
    (session, symbol). Returns the just-closed candle when this tick crosses
    into a new hour, else None -- the caller only acts on a closed candle."""
    key = (session_id, symbol)
    bucket_start = now.replace(minute=0, second=0, microsecond=0)
    current = _candle_buckets.get(key)
    if current is None or current["bucket_start"] != bucket_start:
        _candle_buckets[key] = {
            "bucket_start": bucket_start,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": volume,
        }
        return current
    current["high"] = max(current["high"], price)
    current["low"] = min(current["low"], price)
    current["close"] = price
    current["volume"] += volume
    return None


def _update_4h_candle(session_id: int, symbol: str, price: float, now: datetime) -> dict | None:
    """Same bucketing idea as _update_candle, on a 4-hour boundary (00/04/08/
    12/16/20 UTC) instead of hourly. Only the close matters for the SMA
    trend filter below, so this bucket doesn't bother tracking open/high/low."""
    key = (session_id, symbol)
    bucket_hour = (now.hour // 4) * 4
    bucket_start = now.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
    current = _candle_4h_buckets.get(key)
    if current is None or current["bucket_start"] != bucket_start:
        _candle_4h_buckets[key] = {"bucket_start": bucket_start, "close": price}
        return current
    current["close"] = price
    return None


def _load_4h_trend_if_needed(db: DbSession, session_id: int, symbol: str) -> None:
    key = (session_id, symbol)
    if key in _trend_4h_history:
        return
    saved = load_state(db, session_id, symbol, TREND_4H_HISTORY_KEY)
    closes = saved["closes"] if saved else []
    _trend_4h_history[key] = deque(closes, maxlen=TREND_4H_HISTORY_LENGTH)
    if saved and saved.get("uptrend") is not None:
        _trend_4h_uptrend[key] = saved["uptrend"]


def _update_4h_trend(db: DbSession, session_id: int, symbol: str, closed_4h_close: float) -> None:
    key = (session_id, symbol)
    history = _trend_4h_history[key]
    history.append(closed_4h_close)
    prices = list(history)
    fast = sma(prices, TREND_4H_FAST_PERIOD)
    slow = sma(prices, TREND_4H_SLOW_PERIOD)
    if fast is not None and slow is not None:
        _trend_4h_uptrend[key] = fast > slow
    save_state(
        db, session_id, symbol, TREND_4H_HISTORY_KEY, {"closes": list(history), "uptrend": _trend_4h_uptrend.get(key)}
    )


def get_chart_data(session_id: int) -> dict[str, dict]:
    """Price/volume/indicator series for each tradable coin, over the chart's
    own rolling window (see CHART_HISTORY_LENGTH) -- longer than what the
    live strategies themselves see for regime detection (REGIME_HISTORY_LENGTH),
    since this is for a human to look at, not a separate historical fetch.
    RSI and MACD are computed fresh at every point in that window so they can
    be charted as lines, not just a single latest value."""
    result: dict[str, dict] = {}
    for symbol in TRADABLE_SYMBOLS:
        ticks = list(_chart_histories.get((session_id, symbol), []))
        prices = [t["price"] for t in ticks]
        macd_line, macd_signal, macd_hist = macd_series(prices)
        result[symbol] = {
            "timestamps": [t["timestamp"] for t in ticks],
            "prices": prices,
            "volumes": [t["volume"] for t in ticks],
            "rsi": [float(v) if v is not None else None for v in rsi_series(prices)],
            "macd": macd_line,
            "macd_signal": macd_signal,
            "macd_histogram": macd_hist,
        }
    return result


# A real tick (even a slow one, e.g. Kraken rate-limiting) finishes in well
# under a minute. Holding the lock longer than this means the previous tick
# is stuck, not slow -- e.g. a ccxt network call hanging forever on a
# laptop sleep/wake cycle, which otherwise would block this session's
# trading permanently since the lock never gets released.
STUCK_TICK_SECONDS = 120
_tick_lock_started_at: dict[int, float] = {}


def run_tick(db: DbSession, session_id: int) -> list[str]:
    lock = _tick_locks.setdefault(session_id, threading.Lock())
    if not lock.acquire(blocking=False):
        started = _tick_lock_started_at.get(session_id)
        if started is None or time.monotonic() - started < STUCK_TICK_SECONDS:
            return []
        # Abandon the stuck previous tick and take over.
        lock.release()
        if not lock.acquire(blocking=False):
            return []
    _tick_lock_started_at[session_id] = time.monotonic()
    try:
        return _run_tick_locked(db, session_id)
    finally:
        _tick_lock_started_at.pop(session_id, None)
        lock.release()


def _run_tick_locked(db: DbSession, session_id: int) -> list[str]:
    session = db.get(TradingSession, session_id)
    portfolio = db.get(Portfolio, session_id)
    if session is None or portfolio is None:
        return []

    is_auto = (session.strategy_name or AUTO_STRATEGY) == AUTO_STRATEGY
    sentiment = get_sentiment_state()
    executor = PaperExecutor(db, session_id)
    executed: list[str] = []
    # Fetched upfront (not lazily as each symbol is processed) so the
    # correlation-based sizing below always has every coin's current price
    # available, even for a buy signal on the first symbol in the loop.
    prices: dict[str, float] = {symbol: get_ticker_price(symbol) for symbol in TRADABLE_SYMBOLS}
    correlation_matrix = get_correlation_matrix(TRADABLE_SYMBOLS)
    volumes: dict[str, float] = {}
    for symbol in TRADABLE_SYMBOLS:
        try:
            raw_volume = get_ticker_volume(symbol)
        except Exception:
            raw_volume = None
        volumes[symbol] = _volume_delta(session_id, symbol, raw_volume) if raw_volume is not None else 0.0
        _record_chart_tick(session_id, symbol, prices[symbol], volumes[symbol])

    for symbol in TRADABLE_SYMBOLS:
        price = prices[symbol]

        if is_auto:
            history_key = (session_id, symbol)
            if history_key not in _price_histories:
                saved_history = load_state(db, session_id, symbol, REGIME_HISTORY_KEY)
                initial_prices = saved_history["prices"] if saved_history else []
                _price_histories[history_key] = deque(initial_prices, maxlen=REGIME_HISTORY_LENGTH)
                if saved_history and saved_history.get("regime"):
                    _regime_state[(session_id, symbol)] = {
                        "regime": saved_history["regime"],
                        "active_strategy": REGIME_STRATEGY[saved_history["regime"]],
                    }
            history = _price_histories[history_key]
            history.append(price)
            previous_regime = _regime_state.get((session_id, symbol), {}).get("regime")
            active_strategy_name, regime = pick_strategy(list(history), previous_regime)
            _regime_state[(session_id, symbol)] = {"regime": regime, "active_strategy": active_strategy_name}
            save_state(db, session_id, symbol, REGIME_HISTORY_KEY, {"prices": list(history), "regime": regime})
            candidate_names = list(STRATEGY_BUILDERS.keys())
        else:
            active_strategy_name = session.strategy_name or "grid"
            candidate_names = [active_strategy_name]

        # Position-level stop-loss: independent of any strategy's own exit
        # logic (which can lag a fast drop), and checked before any
        # strategy signal this tick, using the weighted-average entry price
        # PaperExecutor tracks per asset.
        base_asset = symbol.split("/")[0]
        _load_position_owner_if_needed(db, session_id, symbol)
        held_qty = (portfolio.holdings or {}).get(base_asset, 0)
        if held_qty > 0:
            avg_cost = (portfolio.cost_basis or {}).get(base_asset, 0.0)
            stop_loss = check_position_stop_loss(price, avg_cost)
            if stop_loss.triggered:
                fill = executor.place_order(
                    symbol, "sell", 1.0, f"risk: stop-loss triggered ({stop_loss.loss_pct:.1f}% below entry)"
                )
                if fill is not None:
                    executed.append(f"{fill.side} {fill.qty:.6f} {fill.symbol} @ {fill.price:.2f} (stop-loss)")
                    _log_decision(
                        session_id,
                        {
                            "symbol": symbol,
                            "strategy": "risk",
                            "side": "sell",
                            "outcome": "stop_loss_triggered",
                            "detail": f"{stop_loss.loss_pct:.1f}% below entry",
                        },
                    )
                    # The strategies ticking this symbol don't know their
                    # position just got closed out from under them -- without
                    # this, e.g. grid's owned_levels would stay stale and
                    # block a legitimate re-buy later.
                    for strategy_name in candidate_names:
                        key = (session_id, symbol, strategy_name)
                        if key in _strategy_instances:
                            _strategy_instances[key].on_external_sell()
                    _clear_position_owner(db, session_id, symbol)

        position_cost_basis = (portfolio.cost_basis or {}).get(base_asset, 0.0)
        ctx = StrategyContext(
            symbol=symbol,
            price=price,
            cash_usd=portfolio.cash_usd,
            holdings=portfolio.holdings or {},
            pause_new_entries=sentiment.pause_new_entries,
            size_multiplier=sentiment.size_multiplier,
            volume=volumes[symbol],
            cost_basis=position_cost_basis,
        )
        closed_candle = _update_candle(session_id, symbol, price, volumes[symbol], datetime.utcnow())
        _load_4h_trend_if_needed(db, session_id, symbol)
        closed_4h_candle = _update_4h_candle(session_id, symbol, price, datetime.utcnow())
        if closed_4h_candle is not None:
            _update_4h_trend(db, session_id, symbol, closed_4h_candle["close"])

        for strategy_name in candidate_names:
            strategy = _get_strategy(db, session_id, symbol, strategy_name)
            if strategy_name == "trend_momentum":
                # Only reacts once an hourly candle actually closes -- see
                # CANDLE_INTERVAL_SECONDS above for why raw 30s ticks aren't
                # a real "trend" timeframe for this strategy.
                if closed_candle is None:
                    continue
                strategy_ctx = StrategyContext(
                    symbol=symbol,
                    price=closed_candle["close"],
                    cash_usd=portfolio.cash_usd,
                    holdings=portfolio.holdings or {},
                    pause_new_entries=sentiment.pause_new_entries,
                    size_multiplier=sentiment.size_multiplier,
                    cost_basis=position_cost_basis,
                    volume=closed_candle["volume"],
                )
            else:
                strategy_ctx = ctx
            signals = strategy.on_tick(strategy_ctx)
            for signal in signals:
                log_base = {"symbol": signal.symbol, "strategy": strategy_name, "side": signal.side, "reason": signal.reason}

                # A sell from an inactive strategy (e.g. it bought while
                # active, then lost the regime and now wants to exit) always
                # goes through, or a coin bought under a strategy that's no
                # longer active could be stranded with no one left willing to
                # sell it.
                #
                # Buys from a strategy in REGIME_SELF_GATING_STRATEGIES are
                # exempt from the regime gate entirely -- see that constant
                # for the measurements that led there. What remains gated is
                # dca_rebalance, which buys on a schedule rather than on any
                # market condition, so with no gate it would simply spend the
                # pool regardless of what the market is doing.
                if (
                    signal.side == "buy"
                    and strategy_name != active_strategy_name
                    and strategy_name not in REGIME_SELF_GATING_STRATEGIES
                ):
                    _log_decision(session_id, {**log_base, "outcome": "blocked_inactive_strategy"})
                    strategy.on_signal_not_filled()
                    continue
                # trend_momentum's own buy is exempt from the regime gate
                # above, but still has to clear this coarser filter: the 4h
                # timeframe's own fast/slow SMA must also be in an uptrend,
                # not just the 1h one the strategy itself looks at. Unknown
                # (not enough 4h history yet, e.g. right after session
                # start) blocks rather than defaults open -- see
                # CANDLE_4H_INTERVAL_SECONDS above for the backtest evidence.
                if (
                    signal.side == "buy"
                    and strategy_name == "trend_momentum"
                    and _trend_4h_uptrend.get((session_id, symbol)) is not True
                ):
                    _log_decision(session_id, {**log_base, "outcome": "blocked_4h_downtrend"})
                    strategy.on_signal_not_filled()
                    continue
                # A sell is allowed through from the position's actual owner
                # (whichever strategy bought it) or from the currently active
                # strategy (so a regime flip can still hand off the exit) --
                # but not from some other inactive strategy that merely
                # notices nonzero holdings and wants to close them out on its
                # own unrelated exit condition. Unknown ownership (None) stays
                # permissive, matching the pre-existing "never strand a
                # position" behavior.
                owner = _position_owners.get((session_id, signal.symbol))
                if (
                    signal.side == "sell"
                    and owner is not None
                    and strategy_name != owner
                    and strategy_name != active_strategy_name
                ):
                    _log_decision(session_id, {**log_base, "outcome": "blocked_not_position_owner"})
                    strategy.on_signal_not_filled()
                    continue
                # A regime-flip handoff sell (active strategy closing a
                # position it didn't open) is only allowed at a real profit
                # against the *original* owner's cost basis -- otherwise the
                # new strategy's own (possibly unproven-on-this-coin) exit
                # condition ends up unilaterally realizing a loss on a
                # position it never had a thesis for. E.g. trend_momentum
                # has no demonstrated edge on SOL/ETH/XRP in backtest, yet
                # was repeatedly closing grid's patient, profit-seeking dip
                # buys at a small loss the moment a regime flip made it
                # "active" -- undoing exactly the discipline grid's own
                # cost-basis check enforces on itself. The strategy's own
                # position (strategy_name == owner) is exempt: cutting a
                # losing trend fast is the whole point of trend-following,
                # and the 12%/max-drawdown guardrails remain the backstop
                # for a real breakdown either way.
                #
                # Requires the same margin grid's own sell uses, not just
                # "strictly above cost basis" -- a raw price a hair above
                # cost basis still nets a real loss once the ~0.26% sell
                # fee (and slippage) are applied, which is exactly what let
                # a trend_momentum handoff sell realize a small loss on XRP
                # despite "clearing" a zero-margin check.
                if (
                    signal.side == "sell"
                    and owner is not None
                    and strategy_name != owner
                    and position_cost_basis > 0
                    and price < position_cost_basis * (1 + HANDOFF_MIN_PROFIT_MARGIN_PCT / 100)
                ):
                    _log_decision(session_id, {**log_base, "outcome": "blocked_handoff_below_cost_basis"})
                    strategy.on_signal_not_filled()
                    continue
                # News sentiment only ever holds back or shrinks buys -- selling
                # out of a position must never be blocked by a bad-news pause.
                if signal.side == "buy" and sentiment.pause_new_entries:
                    _log_decision(session_id, {**log_base, "outcome": "blocked_sentiment_pause"})
                    strategy.on_signal_not_filled()
                    continue
                size_fraction = signal.size_fraction
                original_fraction = size_fraction
                if signal.side == "buy":
                    size_fraction *= sentiment.size_multiplier
                    # Re-read holdings on every signal, not once per tick --
                    # an earlier buy/sell this same tick (e.g. on BTC) must
                    # already count toward sizing a later one (e.g. on ETH).
                    size_fraction *= correlation_size_multiplier(
                        signal.symbol, portfolio.holdings or {}, prices, correlation_matrix
                    )
                    # Hard ceiling, applied after the soft correlation
                    # discount -- two coins with zero correlation to each
                    # other could otherwise both get bought up to 100% of
                    # the portfolio each.
                    size_fraction *= concentration_size_multiplier(
                        signal.symbol, size_fraction, portfolio.cash_usd, portfolio.holdings or {}, prices
                    )
                    # Choppier-than-usual right now -> smaller bet; calmer
                    # than usual -> a somewhat bigger one.
                    size_fraction *= volatility_size_multiplier(_recent_prices(session_id, signal.symbol))
                fill = executor.place_order(signal.symbol, signal.side, size_fraction, signal.reason)
                if fill is None:
                    _log_decision(session_id, {**log_base, "outcome": "zero_after_sizing"})
                    strategy.on_signal_not_filled()
                    continue
                executed.append(f"{fill.side} {fill.qty:.6f} {fill.symbol} @ {fill.price:.2f} ({signal.reason})")
                entry = {**log_base, "outcome": "executed", "qty": fill.qty, "price": fill.price}
                if signal.side == "buy" and size_fraction < original_fraction * 0.99:
                    entry["shrunk_pct"] = round((1 - size_fraction / original_fraction) * 100, 1)
                _log_decision(session_id, entry)

                if signal.side == "buy":
                    _set_position_owner(db, session_id, signal.symbol, strategy_name)
                else:
                    remaining = (portfolio.holdings or {}).get(base_asset, 0)
                    if remaining <= 1e-9:
                        _clear_position_owner(db, session_id, signal.symbol)

            # Saved after signal processing (not right after on_tick) so a
            # speculative owned_levels/in_position mutation that
            # on_signal_not_filled() just rolled back is never the version
            # that lands in the DB.
            save_state(db, session_id, symbol, strategy_name, strategy.get_state())

    holdings = portfolio.holdings or {}
    total_value = portfolio.cash_usd
    for symbol in TRADABLE_SYMBOLS:
        base_asset = symbol.split("/")[0]
        total_value += holdings.get(base_asset, 0) * prices[symbol]

    hodl_value = _hodl_value(session, prices)
    db.add(PortfolioSnapshot(session_id=session_id, total_value_eur=total_value, hodl_value_eur=hodl_value))

    if session.status == "running":
        if session.target_balance is not None and total_value >= session.target_balance:
            session.status = "target_reached"
            send_desktop_notification(
                "🎯 Célösszeg elérve",
                f"Session #{session_id}: {total_value:.2f} EUR (cél: {session.target_balance:.2f} EUR)",
            )
        else:
            past_values = [
                row[0]
                for row in db.query(PortfolioSnapshot.total_value_eur)
                .filter(PortfolioSnapshot.session_id == session_id)
                .all()
            ]
            risk_check = check_drawdown_limit(total_value, past_values, session.max_drawdown_pct)
            if risk_check.breached:
                session.status = "risk_stopped"
                send_desktop_notification(
                    "🛑 Vészleállás",
                    f"Session #{session_id} leállt: {risk_check.drawdown_pct:.1f}%-os visszaesés a csúcsértéktől",
                )

    db.commit()
    return executed


def _hodl_value(session: TradingSession, prices: dict[str, float]) -> float:
    """What the starting balance would be worth now if it had just bought an
    even split of every tradable coin once, at session start, and never
    traded again -- the baseline the bot is trying to beat."""
    starting_prices = session.starting_prices
    if not starting_prices:
        return session.starting_balance_usd

    share = session.starting_balance_usd / len(TRADABLE_SYMBOLS)
    value = 0.0
    for symbol in TRADABLE_SYMBOLS:
        start_price = starting_prices.get(symbol)
        if not start_price:
            continue
        qty = share / start_price
        value += qty * prices[symbol]
    return value
