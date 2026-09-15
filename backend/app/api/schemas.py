from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class SessionCreate(BaseModel):
    starting_balance_usd: float = 10000.0
    strategy_name: str = "auto"
    target_balance: Optional[float] = None
    max_drawdown_pct: Optional[float] = 20.0


class TargetUpdate(BaseModel):
    target_balance: Optional[float] = None


class PortfolioOut(BaseModel):
    cash_usd: float
    holdings: dict
    # Weighted-average entry price per held asset. Already stored on the
    # Portfolio row for the stop-loss guardrail -- exposing it here is what
    # lets the dashboard show a position's unrealized profit/loss, not just
    # its current value.
    cost_basis: dict = {}

    class Config:
        from_attributes = True


class SessionOut(BaseModel):
    id: int
    created_at: datetime
    ended_at: Optional[datetime]
    status: str
    starting_balance_usd: float
    target_balance: Optional[float]
    max_drawdown_pct: Optional[float]
    strategy_name: str
    portfolio: PortfolioOut


class SnapshotOut(BaseModel):
    timestamp: datetime
    total_value_eur: float
    hodl_value_eur: float

    class Config:
        from_attributes = True


class OrderCreate(BaseModel):
    symbol: str = "BTC/EUR"
    side: Literal["buy", "sell"]
    size_fraction: float
    reason: str = "manual test order"


class FillOut(BaseModel):
    symbol: str
    side: str
    qty: float
    price: float
    fee: float


class TradeOut(BaseModel):
    id: int
    timestamp: datetime
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    reason: Optional[str]
    # Only set on a sell -- the realized profit/loss against the position's
    # weighted-average cost basis at that moment, reconstructed by replaying
    # the trade history (see list_trades). None on a buy, since a buy
    # doesn't close anything yet.
    realized_pnl: Optional[float] = None
    realized_pnl_pct: Optional[float] = None

    class Config:
        from_attributes = True


class BacktestResult(BaseModel):
    strategy_name: str
    symbol: str
    days: int
    total_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    volatility: float
    sharpe_like_ratio: float
    trade_count: int


class MultiCoinBacktestResult(BaseModel):
    strategy_name: str
    symbols: list[str]
    days: int
    total_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    volatility: float
    sharpe_like_ratio: float
    trade_count: int
    hodl_total_return_pct: float
    stopped_early: bool


class PeriodMetrics(BaseModel):
    total_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    volatility: float
    sharpe_like_ratio: float
    trade_count: int


class ValidationResult(BaseModel):
    strategy_name: str
    symbol: str
    train: PeriodMetrics
    test: PeriodMetrics


class PositionSizeOut(BaseModel):
    strategy_name: str
    symbol: str
    days: int
    win_rate: float
    avg_win: float
    avg_loss: float
    reward_risk_ratio: float
    kelly_fraction: float


class MonteCarloOut(BaseModel):
    strategy_name: str
    symbol: str
    days: int
    simulations: int
    confidence: float
    var_pct: float
    cvar_pct: float
    prob_loss_10pct: float
    prob_loss_25pct: float
    prob_loss_50pct: float


class RecommendationCandidate(BaseModel):
    strategy_name: str
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_like_ratio: float
    win_rate_pct: float
    within_risk_band: bool


class RecommendationOut(BaseModel):
    risk_level: str
    recommended_strategy: Optional[str]
    rationale: list[str]
    candidates: list[RecommendationCandidate]


class StrategyPerformanceOut(BaseModel):
    id: int
    strategy_name: str
    source: str
    symbol: str
    period_days: Optional[int]
    created_at: datetime
    total_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    volatility: float
    sharpe_like_ratio: float
    trade_count: int

    class Config:
        from_attributes = True
