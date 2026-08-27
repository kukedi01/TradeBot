from dataclasses import dataclass


@dataclass
class RiskCheckResult:
    breached: bool
    peak_value_eur: float
    drawdown_pct: float


def check_drawdown_limit(
    current_value_eur: float,
    past_values_eur: list[float],
    max_drawdown_pct: float | None,
) -> RiskCheckResult:
    """Independent of any strategy: compares the portfolio's current value
    against the highest value it has ever reached in this session. If it has
    fallen more than max_drawdown_pct below that peak, the session should
    stop -- regardless of what the active strategy thinks it's doing."""
    peak_value_eur = max([current_value_eur, *past_values_eur])
    drawdown_pct = (peak_value_eur - current_value_eur) / peak_value_eur * 100 if peak_value_eur > 0 else 0.0

    breached = max_drawdown_pct is not None and drawdown_pct >= max_drawdown_pct
    return RiskCheckResult(breached=breached, peak_value_eur=peak_value_eur, drawdown_pct=drawdown_pct)


@dataclass
class PositionStopLossResult:
    triggered: bool
    loss_pct: float


# How far a single position can fall below its own average entry price
# before it gets force-closed, independent of what any strategy's own exit
# logic says. A strategy's own exit (death cross, band break, a grid level
# recovering) can lag well behind a fast drop -- this is the dumb, strict
# backstop that doesn't wait for an indicator to catch up. Set tighter than
# the portfolio-wide max_drawdown_pct (which only trips once *everything*
# is down together) but loose enough not to whipsaw on ordinary crypto
# volatility.
STOP_LOSS_PCT = 12.0


def check_position_stop_loss(current_price: float, avg_cost: float) -> PositionStopLossResult:
    """Independent of any strategy: compares one held position's current
    price against its own average entry price (see PaperExecutor's
    weighted-average cost tracking). If it has fallen STOP_LOSS_PCT or more,
    the position should be liquidated regardless of what the strategy that
    opened it currently thinks."""
    if avg_cost <= 0:
        return PositionStopLossResult(triggered=False, loss_pct=0.0)
    loss_pct = (avg_cost - current_price) / avg_cost * 100
    return PositionStopLossResult(triggered=loss_pct >= STOP_LOSS_PCT, loss_pct=loss_pct)


# A single coin's value can never exceed this share of the total portfolio,
# no matter how uncorrelated it looks or how strongly a strategy wants in --
# correlation_size_multiplier only ever *discourages* concentration, it
# never hard-caps it (two coins with 0.0 correlation could otherwise both
# get bought up to 100% each). This is the actual ceiling.
MAX_ASSET_ALLOCATION_PCT = 40.0


def concentration_size_multiplier(
    symbol: str,
    size_fraction: float,
    cash_usd: float,
    holdings: dict[str, float],
    prices: dict[str, float],
) -> float:
    """How much to shrink a buy of `symbol` (already reduced by sentiment
    and correlation sizing, hence taking `size_fraction` rather than
    recomputing from scratch) so it can never push that asset's share of
    the total portfolio value above MAX_ASSET_ALLOCATION_PCT. Returns a
    multiplier in [0, 1], the same convention as correlation_size_multiplier,
    so it composes the same way: size_fraction *= this."""
    base_asset = symbol.split("/")[0]
    total_value = cash_usd + sum(holdings.get(sym.split("/")[0], 0) * price for sym, price in prices.items())
    if total_value <= 0:
        return 1.0

    current_asset_value = holdings.get(base_asset, 0) * prices[symbol]
    max_asset_value = total_value * MAX_ASSET_ALLOCATION_PCT / 100
    headroom = max_asset_value - current_asset_value
    if headroom <= 0:
        return 0.0

    proposed_spend = cash_usd * size_fraction
    if proposed_spend <= 0:
        return 1.0
    return min(1.0, headroom / proposed_spend)
