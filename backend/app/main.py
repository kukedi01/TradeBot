from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_backtest import router as backtest_router
from app.api.routes_news import router as news_router
from app.api.routes_risk import router as risk_router
from app.api.routes_session import router as session_router
from app.api.routes_strategies import router as strategies_router
from app.db.database import SessionLocal, init_db
from app.db.models import MarketFlowSnapshot
from app.market_data.kraken_client import get_daily_high_low, get_ticker_price
from app.scheduler import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(session_router)
app.include_router(strategies_router)
app.include_router(backtest_router)
app.include_router(risk_router)
app.include_router(news_router)


@app.get("/market/ticker/{symbol:path}")
def market_ticker(symbol: str):
    price = get_ticker_price(symbol)
    return {"symbol": symbol, "price": price}


@app.get("/market/daily-range/{symbol:path}")
def market_daily_range(symbol: str):
    high, low = get_daily_high_low(symbol)
    return {"symbol": symbol, "high": high, "low": low}


@app.get("/market/flow")
def market_flow(symbol: str | None = None, limit: int = 200):
    """Collected order-flow history (cumulative volume delta, open interest).
    Read-only: nothing trades on this yet, it's being accumulated so the
    signals can eventually be tested against real history -- see
    market_data/flow.py."""
    db = SessionLocal()
    try:
        query = db.query(MarketFlowSnapshot)
        if symbol:
            query = query.filter(MarketFlowSnapshot.symbol == symbol)
        rows = query.order_by(MarketFlowSnapshot.timestamp.desc()).limit(min(limit, 2000)).all()
        return [
            {
                "timestamp": row.timestamp,
                "symbol": row.symbol,
                "price": row.price,
                "volume_delta": row.volume_delta,
                "cumulative_volume_delta": row.cumulative_volume_delta,
                "trade_count": row.trade_count,
                "open_interest": row.open_interest,
            }
            for row in reversed(rows)
        ]
    finally:
        db.close()
