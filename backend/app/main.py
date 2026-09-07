from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_backtest import router as backtest_router
from app.api.routes_news import router as news_router
from app.api.routes_risk import router as risk_router
from app.api.routes_session import router as session_router
from app.api.routes_strategies import router as strategies_router
from app.db.database import init_db
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
