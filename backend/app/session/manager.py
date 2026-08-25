from datetime import datetime

from sqlalchemy.orm import Session as DbSession

from app.db.models import Portfolio, TradingSession
from app.market_data.kraken_client import get_ticker_price
from app.session.loop import TRADABLE_SYMBOLS


def create_session(
    db: DbSession,
    starting_balance_usd: float,
    strategy_name: str = "auto",
    target_balance: float | None = None,
    max_drawdown_pct: float | None = 20.0,
) -> TradingSession:
    starting_prices = {symbol: get_ticker_price(symbol) for symbol in TRADABLE_SYMBOLS}
    session = TradingSession(
        starting_balance_usd=starting_balance_usd,
        status="running",
        strategy_name=strategy_name,
        target_balance=target_balance,
        max_drawdown_pct=max_drawdown_pct,
        starting_prices=starting_prices,
    )
    db.add(session)
    db.flush()

    portfolio = Portfolio(session_id=session.id, cash_usd=starting_balance_usd, holdings={})
    db.add(portfolio)

    db.commit()
    db.refresh(session)
    return session


def stop_session(db: DbSession, session_id: int) -> TradingSession:
    session = db.get(TradingSession, session_id)
    session.status = "stopped"
    session.ended_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return session


def set_target(db: DbSession, session_id: int, target_balance: float | None) -> TradingSession:
    """Sets a new target on a session and resumes it (used after a target
    was reached and the user chose to keep going instead of withdrawing)."""
    session = db.get(TradingSession, session_id)
    session.target_balance = target_balance
    session.status = "running"
    session.ended_at = None
    db.commit()
    db.refresh(session)
    return session


def get_session(db: DbSession, session_id: int) -> TradingSession | None:
    return db.get(TradingSession, session_id)


def stop_all_sessions(db: DbSession) -> list[TradingSession]:
    """Kill switch: immediately stops every session still in play, regardless
    of what its strategy or the scheduler thinks it's doing."""
    sessions = db.query(TradingSession).filter(TradingSession.status.in_(["running", "target_reached"])).all()
    now = datetime.utcnow()
    for session in sessions:
        session.status = "stopped"
        session.ended_at = now
    db.commit()
    return sessions
