from typing import Callable

from app.strategies.base import Strategy
from app.strategies.dca_rebalance import DcaRebalanceStrategy
from app.strategies.grid import GridStrategy
from app.strategies.trend_momentum import TrendMomentumStrategy


def _build_grid(symbol: str, price: float, size_fraction_override: float | None = None) -> GridStrategy:
    return GridStrategy(
        symbol=symbol,
        lower_bound=price * 0.95,
        upper_bound=price * 1.05,
        grid_levels=10,
        order_size_fraction=size_fraction_override if size_fraction_override is not None else 0.1,
        # 0.85%, not the class default 0.3% -- see GridStrategy's docstring for
        # the sweep. The short version: 0.3% sits *below* the ~0.62%
        # round-trip fee+slippage cost, so the hysteresis was letting through
        # exactly the trades that cannot pay for themselves.
        min_move_pct=0.85,
    )


def _build_dca_rebalance(
    symbol: str, price: float, size_fraction_override: float | None = None
) -> DcaRebalanceStrategy:
    kwargs = {}
    if size_fraction_override is not None:
        kwargs["dca_size_fraction"] = size_fraction_override
    return DcaRebalanceStrategy(symbol=symbol, **kwargs)


def _build_trend_momentum(
    symbol: str, price: float, size_fraction_override: float | None = None
) -> TrendMomentumStrategy:
    kwargs = {}
    if size_fraction_override is not None:
        kwargs["order_size_fraction"] = size_fraction_override
    return TrendMomentumStrategy(symbol=symbol, **kwargs)


STRATEGY_BUILDERS: dict[str, Callable[..., Strategy]] = {
    "grid": _build_grid,
    "dca_rebalance": _build_dca_rebalance,
    "trend_momentum": _build_trend_momentum,
}
