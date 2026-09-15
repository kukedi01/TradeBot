"""Shared fixtures for testing session/loop.py's tick orchestration.

That module is the one place where every other part meets -- regime
selection, position ownership, sentiment, sizing, guardrails, executor -- and
until now it had no tests at all, despite being the largest module in the
project. Both of the most expensive bugs found so far lived here or in the
backtest engine's mirror of it: a regime gate that locked grid out of ~30%
of every session, and a handoff rule the backtest didn't replicate. Neither
was catchable by the strategy-level tests, because both were about how the
pieces are wired together, not about any one piece.

The fixtures below make that testable without touching Kraken or the real
database: an in-memory SQLite session, scripted strategies injected into the
instance cache so no network-dependent Kelly lookup ever runs, and stubs for
every outbound call the tick makes.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Portfolio, TradingSession
from app.execution import paper_executor
from app.news.reactor import SentimentState
from app.session import loop as loop_module
from app.strategies.base import Strategy

TEST_PRICES = {"BTC/EUR": 60000.0, "ETH/EUR": 2000.0, "SOL/EUR": 100.0, "XRP/EUR": 1.0}


class ScriptedStrategy(Strategy):
    """Emits exactly the signals a test hands it, once, on the first tick.

    Real strategies decide when to fire from indicator state, which is
    precisely what these tests must not depend on -- the behavior under test
    is what run_tick does *with* a signal (execute it, block it, shrink it),
    not whether a given price series produces one.
    """

    def __init__(self, name: str, signals=None):
        self.name = name
        self._signals = list(signals or [])
        self.not_filled_count = 0
        self.external_sell_count = 0

    def on_tick(self, ctx):
        signals, self._signals = self._signals, []
        return signals

    def on_signal_not_filled(self) -> None:
        self.not_filled_count += 1

    def on_external_sell(self) -> None:
        self.external_sell_count += 1


@pytest.fixture
def db():
    """A fresh in-memory database per test, with every table created."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def make_session(db):
    """Creates a running session with a funded portfolio and returns its id."""

    def _make(
        starting_balance: float = 1000.0,
        holdings: dict | None = None,
        cost_basis: dict | None = None,
        cash: float | None = None,
        target_balance: float | None = None,
        max_drawdown_pct: float | None = 20.0,
        strategy_name: str = "auto",
    ) -> int:
        session = TradingSession(
            status="running",
            starting_balance_usd=starting_balance,
            target_balance=target_balance,
            max_drawdown_pct=max_drawdown_pct,
            strategy_name=strategy_name,
            starting_prices=dict(TEST_PRICES),
        )
        db.add(session)
        db.flush()
        db.add(
            Portfolio(
                session_id=session.id,
                cash_usd=starting_balance if cash is None else cash,
                holdings=holdings or {},
                cost_basis=cost_basis or {},
            )
        )
        db.commit()
        return session.id

    return _make


@pytest.fixture
def loop_env(monkeypatch):
    """Stubs every outbound call run_tick makes and clears the module-level
    caches, so tests can't leak state into each other through them."""
    for cache in (
        loop_module._strategy_instances,
        loop_module._price_histories,
        loop_module._regime_state,
        loop_module._chart_histories,
        loop_module._last_raw_volume,
        loop_module._position_owners,
        loop_module._tick_locks,
        loop_module._candle_buckets,
        loop_module._candle_4h_buckets,
        loop_module._trend_4h_history,
        loop_module._trend_4h_uptrend,
    ):
        cache.clear()

    prices = dict(TEST_PRICES)
    monkeypatch.setattr(loop_module, "get_ticker_price", lambda symbol: prices[symbol])
    # PaperExecutor re-fetches the price itself when filling, from its own
    # module-level import, so it needs stubbing separately -- otherwise every
    # order in these tests would hit Kraken for real.
    monkeypatch.setattr(paper_executor, "get_ticker_price", lambda symbol: prices[symbol])
    monkeypatch.setattr(loop_module, "get_ticker_volume", lambda symbol: 100.0)
    monkeypatch.setattr(loop_module, "get_correlation_matrix", lambda symbols: {})
    monkeypatch.setattr(loop_module, "correlation_size_multiplier", lambda *a, **k: 1.0)
    monkeypatch.setattr(loop_module, "concentration_size_multiplier", lambda *a, **k: 1.0)
    monkeypatch.setattr(loop_module, "volatility_size_multiplier", lambda *a, **k: 1.0)
    monkeypatch.setattr(loop_module, "send_desktop_notification", lambda *a, **k: None)
    # In auto mode every strategy is built for every symbol, and building one
    # asks Kelly for a size -- which runs a fresh 150-day backtest against
    # Kraken. Without this stub a single tick fires a dozen live backtests
    # and the suite hangs instead of failing.
    monkeypatch.setattr(loop_module, "compute_kelly_size_for_strategy", lambda *a, **k: 0.5)
    # Order-flow collection is recording-only and talks to two venues; it
    # must never influence or break a tick, so it's stubbed out entirely.
    monkeypatch.setattr(loop_module, "_record_market_flow", lambda *a, **k: None)
    monkeypatch.setattr(
        loop_module,
        "get_sentiment_state",
        lambda: SentimentState(avg_sentiment=0.0, headline_count=0, pause_new_entries=False, size_multiplier=1.0),
    )

    class Env:
        def __init__(self):
            self.prices = prices

        def set_regime(self, active_strategy: str, regime: str = "trending"):
            monkeypatch.setattr(loop_module, "pick_strategy", lambda *a, **k: (active_strategy, regime))

        def set_sentiment(self, **kwargs):
            defaults = {
                "avg_sentiment": 0.0,
                "headline_count": 0,
                "pause_new_entries": False,
                "size_multiplier": 1.0,
            }
            defaults.update(kwargs)
            monkeypatch.setattr(loop_module, "get_sentiment_state", lambda: SentimentState(**defaults))

        def install(self, session_id: int, symbol: str, strategies: dict[str, ScriptedStrategy]):
            """Pre-seeds the strategy cache so _get_strategy never builds a
            real instance (which would trigger a live Kelly backtest)."""
            for name, strategy in strategies.items():
                loop_module._strategy_instances[(session_id, symbol, name)] = strategy

        def set_4h_uptrend(self, session_id: int, symbol: str, value: bool):
            loop_module._trend_4h_uptrend[(session_id, symbol)] = value

        def arm_hourly_candle_close(self, session_id: int, symbol: str, price: float = 60000.0):
            """Makes the next tick close an hourly candle for this symbol.

            trend_momentum is only ticked when one actually closes (its 5/20
            periods mean hours, not 30-second ticks), so without this it is
            simply skipped and no test of its gating can ever reach it.
            Seeding a bucket stamped to the previous hour makes the next
            tick roll over into a new one and hand back this closed candle.
            """
            previous_hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
            loop_module._candle_buckets[(session_id, symbol)] = {
                "bucket_start": previous_hour,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 100.0,
            }

        def set_owner(self, session_id: int, symbol: str, owner: str):
            loop_module._position_owners[(session_id, symbol)] = owner

        def decisions(self, db_session, session_id: int):
            return loop_module.get_decision_log(db_session, session_id)

        def outcomes(self, db_session, session_id: int, symbol: str | None = None):
            return [
                d["outcome"]
                for d in loop_module.get_decision_log(db_session, session_id)
                if symbol is None or d["symbol"] == symbol
            ]

    return Env()
