from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from app.api.schemas import (
    FillOut,
    OrderCreate,
    PortfolioOut,
    SessionCreate,
    SessionOut,
    SnapshotOut,
    TargetUpdate,
    TradeOut,
)
from app.db.database import SessionLocal
from app.db.models import Portfolio, PortfolioSnapshot, Trade, TradingSession
from app.execution.paper_executor import PaperExecutor
from app.session import manager
from app.session.loop import get_chart_data, get_decision_log, get_regime_state, get_strategy_plan, run_tick

router = APIRouter(prefix="/session", tags=["session"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _to_out(session: TradingSession, portfolio: Portfolio) -> SessionOut:
    return SessionOut(
        id=session.id,
        created_at=session.created_at,
        ended_at=session.ended_at,
        status=session.status,
        starting_balance_usd=session.starting_balance_usd,
        target_balance=session.target_balance,
        max_drawdown_pct=session.max_drawdown_pct,
        strategy_name=session.strategy_name or "grid",
        portfolio=PortfolioOut.model_validate(portfolio),
    )


@router.post("", response_model=SessionOut)
def start_session(payload: SessionCreate, db: DbSession = Depends(get_db)):
    session = manager.create_session(
        db,
        payload.starting_balance_usd,
        payload.strategy_name,
        payload.target_balance,
        payload.max_drawdown_pct,
    )
    portfolio = db.get(Portfolio, session.id)
    return _to_out(session, portfolio)


@router.post("/stop-all", response_model=list[SessionOut])
def stop_all_sessions(db: DbSession = Depends(get_db)):
    """Kill switch -- immediately stops every session still running or
    awaiting a target-reached decision."""
    sessions = manager.stop_all_sessions(db)
    return [_to_out(session, db.get(Portfolio, session.id)) for session in sessions]


@router.get("/active", response_model=SessionOut | None)
def get_active_session(db: DbSession = Depends(get_db)):
    """The most recently created session still in play (running or waiting on
    a target-reached decision), so the frontend can reconnect to it after a
    page reload instead of losing track of it."""
    session = (
        db.query(TradingSession)
        .filter(TradingSession.status.in_(["running", "target_reached"]))
        .order_by(TradingSession.created_at.desc())
        .first()
    )
    if session is None:
        return None
    portfolio = db.get(Portfolio, session.id)
    return _to_out(session, portfolio)


@router.post("/{session_id}/stop", response_model=SessionOut)
def stop_session(session_id: int, db: DbSession = Depends(get_db)):
    session = manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = manager.stop_session(db, session_id)
    portfolio = db.get(Portfolio, session.id)
    return _to_out(session, portfolio)


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: int, db: DbSession = Depends(get_db)):
    session = manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    portfolio = db.get(Portfolio, session.id)
    return _to_out(session, portfolio)


@router.post("/{session_id}/target", response_model=SessionOut)
def set_target(session_id: int, payload: TargetUpdate, db: DbSession = Depends(get_db)):
    session = manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = manager.set_target(db, session_id, payload.target_balance)
    portfolio = db.get(Portfolio, session.id)
    return _to_out(session, portfolio)


@router.post("/{session_id}/order", response_model=FillOut)
def place_order(session_id: int, payload: OrderCreate, db: DbSession = Depends(get_db)):
    session = manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    executor = PaperExecutor(db, session_id)
    fill = executor.place_order(payload.symbol, payload.side, payload.size_fraction, payload.reason)
    if fill is None:
        raise HTTPException(status_code=400, detail="Order size too small to result in a non-zero trade")
    return FillOut(symbol=fill.symbol, side=fill.side, qty=fill.qty, price=fill.price, fee=fill.fee)


@router.get("/{session_id}/trades", response_model=list[TradeOut])
def list_trades(session_id: int, db: DbSession = Depends(get_db)):
    """Reconstructs each sell's realized P&L by replaying the trade history
    with the same weighted-average cost-basis formula PaperExecutor uses
    live -- computed here rather than stored on the Trade row, so no schema
    change (and no cripto.db reset, losing existing history) is needed."""
    trades = db.query(Trade).filter(Trade.session_id == session_id).order_by(Trade.timestamp).all()
    avg_cost: dict[str, float] = {}
    held_qty: dict[str, float] = {}
    result: list[TradeOut] = []
    for t in trades:
        base_asset = t.symbol.split("/")[0]
        realized_pnl = None
        realized_pnl_pct = None
        prev_qty = held_qty.get(base_asset, 0.0)
        if t.side == "buy":
            prev_cost = avg_cost.get(base_asset, 0.0)
            avg_cost[base_asset] = (prev_cost * prev_qty + t.price * t.qty) / (prev_qty + t.qty)
            held_qty[base_asset] = prev_qty + t.qty
        else:
            cost = avg_cost.get(base_asset, 0.0)
            realized_pnl = (t.price - cost) * t.qty - t.fee
            if cost > 0:
                realized_pnl_pct = (t.price - cost) / cost * 100
            held_qty[base_asset] = prev_qty - t.qty
        result.append(
            TradeOut(
                id=t.id,
                timestamp=t.timestamp,
                symbol=t.symbol,
                side=t.side,
                qty=t.qty,
                price=t.price,
                fee=t.fee,
                reason=t.reason,
                realized_pnl=realized_pnl,
                realized_pnl_pct=realized_pnl_pct,
            )
        )
    return result


# How much recent history the equity chart gets at full (~30s tick)
# resolution, regardless of which period is requested -- today's exact
# wiggle is always worth showing in full, even on a "1 year" view. Anything
# older than this is thinned, which is what keeps the payload small no
# matter how long the session has been running (22 215 points / 2.5 MB after
# 8 days running, before this existed).
SNAPSHOT_RECENT_HOURS = 6

# period key -> (how far back it reaches, bucket width for the thinned part).
# The bucket width is chosen so every period returns roughly the same number
# of points (a few hundred) regardless of span -- a wider period means a
# coarser bucket, not a bigger response.
SNAPSHOT_PERIODS: dict[str, tuple[int, int]] = {
    "1h": (1, 60),  # 1 hour back, bucket doesn't matter -- entirely within the full-res window
    "1d": (24, 5 * 60),
    "1w": (7 * 24, 60 * 60),
    "1m": (30 * 24, 6 * 60 * 60),
    "6m": (182 * 24, 24 * 60 * 60),
    "1y": (365 * 24, 2 * 24 * 60 * 60),
}
DEFAULT_SNAPSHOT_PERIOD = "1d"


@router.get("/{session_id}/snapshots", response_model=list[SnapshotOut])
def list_snapshots(session_id: int, period: str = DEFAULT_SNAPSHOT_PERIOD, db: DbSession = Depends(get_db)):
    span_hours, bucket_seconds = SNAPSHOT_PERIODS.get(period, SNAPSHOT_PERIODS[DEFAULT_SNAPSHOT_PERIOD])
    now = datetime.utcnow()
    period_start = now - timedelta(hours=span_hours)
    # The full-res window never exceeds the requested period itself -- an
    # "1 hour" request stays entirely full-resolution rather than being
    # thinned against a 6h window wider than what was asked for.
    recent_start = now - timedelta(hours=min(SNAPSHOT_RECENT_HOURS, span_hours))

    older: list[PortfolioSnapshot] = []
    if period_start < recent_start:
        # Older-than-recent rows are thinned to one point per bucket (the
        # last snapshot actually recorded in that bucket, not an average --
        # a real value, just sampled less often). Bucketing by
        # floor(unix_seconds / bucket_seconds) works for any bucket width,
        # unlike strftime's fixed hour/day/week units, so one query serves
        # every period. MAX(id) breaks ties since ids are inserted in
        # timestamp order, and selecting by id avoids a second round-trip.
        thinned_ids = [
            row[0]
            for row in db.execute(
                text(
                    """
                    SELECT MAX(id)
                    FROM portfolio_snapshots
                    WHERE session_id = :session_id AND timestamp >= :period_start AND timestamp < :recent_start
                    GROUP BY CAST(strftime('%s', timestamp) AS INTEGER) / :bucket_seconds
                    """
                ),
                {
                    "session_id": session_id,
                    "period_start": period_start,
                    "recent_start": recent_start,
                    "bucket_seconds": bucket_seconds,
                },
            ).all()
        ]
        if thinned_ids:
            older = (
                db.query(PortfolioSnapshot)
                .filter(PortfolioSnapshot.id.in_(thinned_ids))
                .order_by(PortfolioSnapshot.timestamp)
                .all()
            )

    recent = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.session_id == session_id,
            PortfolioSnapshot.timestamp >= max(recent_start, period_start),
        )
        .order_by(PortfolioSnapshot.timestamp)
        .all()
    )
    return older + recent


@router.get("/{session_id}/regime")
def get_regime(session_id: int, db: DbSession = Depends(get_db)):
    session = manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"per_symbol": get_regime_state(session_id)}


@router.get("/{session_id}/decisions")
def get_decisions(session_id: int, db: DbSession = Depends(get_db)):
    """Every recent signal a strategy produced and what happened to it --
    executed, or blocked/shrunk and why (inactive strategy, sentiment pause,
    correlation/concentration sizing, stop-loss). The trade list only shows
    what *did* happen; this is the "why didn't it trade" view."""
    session = manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"decisions": get_decision_log(db, session_id)}


@router.get("/{session_id}/plan")
def get_plan(session_id: int, db: DbSession = Depends(get_db)):
    """What each coin is waiting for, as concrete prices -- the "why isn't it
    buying, the price looks low?" view. See loop.get_strategy_plan."""
    session = manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"per_symbol": get_strategy_plan(db, session_id)}


@router.get("/{session_id}/strategy-performance")
def strategy_performance(session_id: int, db: DbSession = Depends(get_db)):
    """Which strategy actually made or lost money in this session.

    Attribution comes from each trade's `reason` prefix ("grid: ...",
    "trend_momentum: ...", "risk: stop-loss ...") rather than a dedicated
    column, so it works on every trade already recorded instead of only on
    ones made after this view existed.

    A sell's realized P&L is credited to whichever strategy closed the
    position, using the same weighted-average cost basis PaperExecutor keeps
    live -- so a strategy that buys well but hands the exit to another
    (which the regime handoff allows) shows the cost of that, not the credit.
    """
    session = manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    trades = db.query(Trade).filter(Trade.session_id == session_id).order_by(Trade.timestamp).all()
    avg_cost: dict[str, float] = {}
    held_qty: dict[str, float] = {}
    stats: dict[str, dict] = {}

    for trade in trades:
        strategy = (trade.reason or "unknown").split(":")[0].strip() or "unknown"
        row = stats.setdefault(
            strategy,
            {"strategy": strategy, "buys": 0, "sells": 0, "realized_pnl": 0.0, "fees": 0.0, "wins": 0, "losses": 0},
        )
        row["fees"] += trade.fee

        base_asset = trade.symbol.split("/")[0]
        previous_qty = held_qty.get(base_asset, 0.0)
        if trade.side == "buy":
            previous_cost = avg_cost.get(base_asset, 0.0)
            avg_cost[base_asset] = (previous_cost * previous_qty + trade.price * trade.qty) / (
                previous_qty + trade.qty
            )
            held_qty[base_asset] = previous_qty + trade.qty
            row["buys"] += 1
        else:
            realized = (trade.price - avg_cost.get(base_asset, 0.0)) * trade.qty - trade.fee
            held_qty[base_asset] = previous_qty - trade.qty
            row["sells"] += 1
            row["realized_pnl"] += realized
            if realized > 0:
                row["wins"] += 1
            else:
                row["losses"] += 1

    for row in stats.values():
        closed = row["wins"] + row["losses"]
        row["win_rate_pct"] = (row["wins"] / closed * 100) if closed else None
        row["realized_pnl"] = round(row["realized_pnl"], 4)
        row["fees"] = round(row["fees"], 4)

    return sorted(stats.values(), key=lambda row: row["realized_pnl"], reverse=True)


@router.get("/{session_id}/chart-data")
def get_chart_data_endpoint(session_id: int, db: DbSession = Depends(get_db)):
    """Price/volume/RSI/MACD series per coin, over the same short rolling
    window the live strategies themselves see (see loop.get_chart_data)."""
    session = manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return get_chart_data(session_id)


@router.post("/{session_id}/tick")
def tick_now(session_id: int, db: DbSession = Depends(get_db)):
    session = manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    executed = run_tick(db, session_id)
    return {"executed": executed}
