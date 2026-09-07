from sqlalchemy.orm import Session as DbSession

from app.db.models import StrategyState

# Sentinel strategy_name used to persist the recent price history that
# regime detection watches, which isn't owned by any one strategy.
REGIME_HISTORY_KEY = "_regime_history"

# Sentinel strategy_name used to persist which strategy currently owns the
# open position on a symbol (see session/loop.py's _position_owners) -- a
# backend restart wipes the in-memory dict, and without persisting it, every
# position's ownership would revert to "unknown" (permissive) right after a
# restart, letting any strategy sell it -- exactly the hijacking bug that
# tracking ownership was meant to prevent in the first place.
POSITION_OWNER_KEY = "_position_owner"

# Sentinel strategy_name used to persist the rolling 4-hour-candle close
# history that trend_momentum's coarser trend-agreement filter watches (see
# session/loop.py's _trend_4h_history) -- without this, a backend restart
# would force a fresh ~80-hour (20 4h-candles) warmup before the filter could
# confirm anything again, same reasoning as REGIME_HISTORY_KEY above.
TREND_4H_HISTORY_KEY = "_trend_4h_history"


def save_state(db: DbSession, session_id: int, symbol: str, strategy_name: str, state: dict) -> None:
    row = db.get(StrategyState, (session_id, symbol, strategy_name))
    if row is None:
        row = StrategyState(session_id=session_id, symbol=symbol, strategy_name=strategy_name, state=state)
        db.add(row)
    else:
        row.state = state
    db.commit()


def load_state(db: DbSession, session_id: int, symbol: str, strategy_name: str) -> dict | None:
    row = db.get(StrategyState, (session_id, symbol, strategy_name))
    return row.state if row is not None else None
