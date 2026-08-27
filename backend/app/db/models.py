from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String

from app.db.database import Base


class TradingSession(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String, default="running")
    starting_balance_usd = Column(Float, nullable=False)
    target_balance = Column(Float, nullable=True)
    risk_level = Column(String, nullable=True)
    strategy_name = Column(String, nullable=True)
    # Price of each tradable symbol at session creation, so a HODL baseline
    # (buy an even split once, never trade again) can be valued later without
    # needing to look up historical OHLCV data.
    starting_prices = Column(JSON, nullable=True)
    # Independent of any strategy: if the portfolio ever falls this many
    # percent below its own peak value, the session auto-stops. Protects
    # capital even if the active strategy's logic is wrong.
    max_drawdown_pct = Column(Float, nullable=True, default=20.0)


class Portfolio(Base):
    __tablename__ = "portfolios"

    session_id = Column(Integer, primary_key=True)
    cash_usd = Column(Float, nullable=False)
    holdings = Column(JSON, default=dict)
    # Weighted-average entry price per held asset (same formula the backtest
    # engine uses to classify win/loss trades) -- lets the position-level
    # stop-loss guardrail tell how far a coin has fallen from where it was
    # actually bought, not just from its current price.
    cost_basis = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    qty = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fee = Column(Float, nullable=False)
    reason = Column(String, nullable=True)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    total_value_eur = Column(Float, nullable=False)
    hodl_value_eur = Column(Float, nullable=False)


class StrategyState(Base):
    """Persisted memory for one (session, symbol, strategy) so a backend
    restart doesn't wipe a strategy's grid levels, moving-average history,
    etc. strategy_name "_regime_history" is a special row used to remember
    the recent price history used for regime detection, not a real
    strategy's own state."""

    __tablename__ = "strategy_states"

    session_id = Column(Integer, primary_key=True)
    symbol = Column(String, primary_key=True)
    strategy_name = Column(String, primary_key=True)
    state = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StrategyPerformanceRecord(Base):
    __tablename__ = "strategy_performance_records"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    period_days = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    total_return_pct = Column(Float, nullable=False)
    max_drawdown_pct = Column(Float, nullable=False)
    win_rate_pct = Column(Float, nullable=False)
    volatility = Column(Float, nullable=False)
    sharpe_like_ratio = Column(Float, nullable=False)
    trade_count = Column(Integer, nullable=False)
