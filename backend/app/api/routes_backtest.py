from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from app.api.schemas import (
    BacktestResult,
    MonteCarloOut,
    MultiCoinBacktestResult,
    PositionSizeOut,
    StrategyPerformanceOut,
    ValidationResult,
)
from app.backtest.data_loader import fetch_historical_ohlcv, fetch_ohlcv_between
from app.backtest.engine import run_backtest, run_multi_coin_backtest
from app.backtest.metrics import compute_metrics
from app.backtest.validation import run_train_test_split
from app.constants import TRADABLE_SYMBOLS
from app.db.database import SessionLocal
from app.db.models import StrategyPerformanceRecord
from app.risk.monte_carlo import run_monte_carlo
from app.risk.position_sizing import kelly_fraction

router = APIRouter(prefix="/backtest", tags=["backtest"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/{strategy_name}", response_model=BacktestResult)
def run_backtest_endpoint(
    strategy_name: str,
    symbol: str = "BTC/EUR",
    days: int = 30,
    starting_balance_usd: float = 10000.0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: DbSession = Depends(get_db),
):
    if start_date and end_date:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        candles = fetch_ohlcv_between(symbol, start, end)
        days = (end - start).days
    else:
        candles = fetch_historical_ohlcv(symbol, days=days)

    result = run_backtest(strategy_name, symbol, candles, starting_balance_usd)
    metrics = compute_metrics(result)

    record = StrategyPerformanceRecord(
        strategy_name=strategy_name,
        source="backtest",
        symbol=symbol,
        period_days=days,
        **metrics,
    )
    db.add(record)
    db.commit()

    return BacktestResult(strategy_name=strategy_name, symbol=symbol, days=days, **metrics)


@router.post("/{strategy_name}/validate", response_model=ValidationResult)
def validate_backtest_endpoint(
    strategy_name: str,
    symbol: str = "BTC/EUR",
    days: int = 150,
    starting_balance_usd: float = 10000.0,
    split_ratio: float = 0.7,
):
    candles = fetch_historical_ohlcv(symbol, days=days)
    result = run_train_test_split(strategy_name, symbol, candles, starting_balance_usd, split_ratio)
    return ValidationResult(strategy_name=strategy_name, symbol=symbol, **result)


@router.post("/{strategy_name}/position-size", response_model=PositionSizeOut)
def position_size_endpoint(
    strategy_name: str,
    symbol: str = "BTC/EUR",
    days: int = 150,
    starting_balance_usd: float = 10000.0,
):
    candles = fetch_historical_ohlcv(symbol, days=days)
    result = run_backtest(strategy_name, symbol, candles, starting_balance_usd)
    sizing = kelly_fraction(result["win_pnls"], result["loss_pnls"])
    return PositionSizeOut(strategy_name=strategy_name, symbol=symbol, days=days, **sizing)


@router.post("/{strategy_name}/monte-carlo", response_model=MonteCarloOut)
def monte_carlo_endpoint(
    strategy_name: str,
    symbol: str = "BTC/EUR",
    days: int = 150,
    starting_balance_usd: float = 10000.0,
    num_simulations: int = 1000,
    confidence: float = 0.95,
):
    candles = fetch_historical_ohlcv(symbol, days=days)
    result = run_backtest(strategy_name, symbol, candles, starting_balance_usd)
    sim = run_monte_carlo(result["equity_curve"], num_simulations, confidence)
    return MonteCarloOut(strategy_name=strategy_name, symbol=symbol, days=days, **sim)


@router.post("/multi-coin/{strategy_mode}", response_model=MultiCoinBacktestResult)
def run_multi_coin_backtest_endpoint(
    strategy_mode: str,
    days: int = 150,
    starting_balance_usd: float = 10000.0,
    max_drawdown_pct: Optional[float] = 20.0,
):
    """Backtests a full multi-coin session (see run_multi_coin_backtest's
    docstring) -- shared cash pool across all 4 tradable coins, with the
    same correlation/concentration sizing and stop-loss a live session
    applies, unlike the single-symbol /backtest/{strategy_name} above."""
    candles_by_symbol = {symbol: fetch_historical_ohlcv(symbol, days=days) for symbol in TRADABLE_SYMBOLS}
    result = run_multi_coin_backtest(strategy_mode, candles_by_symbol, starting_balance_usd, max_drawdown_pct)
    metrics = compute_metrics(result)
    hodl_metrics = compute_metrics(
        {
            "starting_balance_usd": starting_balance_usd,
            "equity_curve": result["hodl_equity_curve"],
            "win_pnls": [],
            "loss_pnls": [],
            "trades": [],
        }
    )
    return MultiCoinBacktestResult(
        strategy_name=strategy_mode,
        symbols=TRADABLE_SYMBOLS,
        days=days,
        hodl_total_return_pct=hodl_metrics["total_return_pct"],
        stopped_early=result["stopped_early"],
        **metrics,
    )


@router.get("", response_model=list[StrategyPerformanceOut])
def list_backtests(db: DbSession = Depends(get_db)):
    return (
        db.query(StrategyPerformanceRecord)
        .order_by(StrategyPerformanceRecord.created_at.desc())
        .limit(20)
        .all()
    )
