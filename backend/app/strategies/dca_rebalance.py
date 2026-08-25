from app.strategies.base import Strategy, StrategyContext, TradeSignal


class DcaRebalanceStrategy(Strategy):
    """Buys a fixed amount on a regular schedule (dollar-cost averaging),
    and sells some of the position down if it drifts too far above the
    target allocation of the portfolio."""

    name = "dca_rebalance"

    def __init__(
        self,
        symbol: str,
        target_allocation_pct: float = 0.5,
        drift_threshold_pct: float = 0.1,
        dca_interval_ticks: int = 10,
        dca_size_fraction: float = 0.05,
    ):
        self.symbol = symbol
        self.target_allocation_pct = target_allocation_pct
        self.drift_threshold_pct = drift_threshold_pct
        self.dca_interval_ticks = dca_interval_ticks
        self.dca_size_fraction = dca_size_fraction
        self.tick_count = 0

    def on_tick(self, ctx: StrategyContext) -> list[TradeSignal]:
        self.tick_count += 1
        base_asset = self.symbol.split("/")[0]
        held_qty = ctx.holdings.get(base_asset, 0)
        held_value = held_qty * ctx.price
        total_value = held_value + ctx.cash_usd
        current_allocation = held_value / total_value if total_value > 0 else 0

        if current_allocation - self.target_allocation_pct > self.drift_threshold_pct:
            return [
                TradeSignal(
                    symbol=self.symbol,
                    side="sell",
                    size_fraction=0.2,
                    reason=(
                        f"dca_rebalance: allocation {current_allocation:.0%} above "
                        f"target {self.target_allocation_pct:.0%}, rebalancing down"
                    ),
                )
            ]

        if self.tick_count % self.dca_interval_ticks == 0 and ctx.cash_usd > 0:
            return [
                TradeSignal(
                    symbol=self.symbol,
                    side="buy",
                    size_fraction=self.dca_size_fraction,
                    reason=f"dca_rebalance: scheduled DCA buy (tick {self.tick_count})",
                )
            ]

        return []
