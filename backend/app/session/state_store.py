from sqlalchemy.orm import Session as DbSession

from app.db.models import StrategyState

# Sentinel strategy_name used to persist the recent price history that
# regime detection watches, which isn't owned by any one strategy.
REGIME_HISTORY_KEY = "_regime_history"


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
