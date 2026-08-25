from app.strategies.base import Strategy, StrategyContext, TradeSignal


class GridStrategy(Strategy):
    """Buys when price dips into a new lower grid level, sells when price
    rises back out of a level it previously bought at. If price stays
    outside the band for too long (e.g. a sustained trend carries it away
    for good), the grid re-centers itself around the current price instead
    of sitting permanently inactive.

    Requires a minimum price move since the last trade before firing again,
    so tiny tick-to-tick noise near a level boundary can't make it flip
    back and forth and churn fees on trades that aren't really "dips" or
    "rises" at all.
    """

    name = "grid"

    def __init__(
        self,
        symbol: str,
        lower_bound: float,
        upper_bound: float,
        grid_levels: int,
        order_size_fraction: float = 0.1,
        recenter_after_ticks_out_of_range: int = 4,
        min_move_pct: float = 0.3,
    ):
        self.symbol = symbol
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.grid_levels = grid_levels
        self.step = (upper_bound - lower_bound) / grid_levels
        self.order_size_fraction = order_size_fraction
        self.recenter_after_ticks_out_of_range = recenter_after_ticks_out_of_range
        self.min_move_pct = min_move_pct
        self.owned_levels: set[int] = set()
        self.last_level: int | None = None
        self.last_trade_price: float | None = None
        self.ticks_out_of_range = 0

    def _level(self, price: float) -> int:
        return int((price - self.lower_bound) // self.step)

    def _far_enough_from_last_trade(self, price: float) -> bool:
        if self.last_trade_price is None:
            return True
        return abs(price - self.last_trade_price) / self.last_trade_price * 100 >= self.min_move_pct

    def _recenter(self, price: float) -> None:
        band_width = self.upper_bound - self.lower_bound
        half = band_width / 2
        self.lower_bound = price - half
        self.upper_bound = price + half
        self.step = band_width / self.grid_levels
        self.owned_levels = set()
        self.last_level = None
        self.ticks_out_of_range = 0

    def on_tick(self, ctx: StrategyContext) -> list[TradeSignal]:
        if not (self.lower_bound <= ctx.price <= self.upper_bound):
            self.ticks_out_of_range += 1
            if self.ticks_out_of_range >= self.recenter_after_ticks_out_of_range:
                self._recenter(ctx.price)
            self.last_level = None
            return []

        self.ticks_out_of_range = 0
        level = self._level(ctx.price)
        signals: list[TradeSignal] = []

        if self.last_level is not None and self._far_enough_from_last_trade(ctx.price):
            if level < self.last_level and level not in self.owned_levels:
                self.owned_levels.add(level)
                self.last_trade_price = ctx.price
                signals.append(
                    TradeSignal(
                        symbol=self.symbol,
                        side="buy",
                        size_fraction=self.order_size_fraction,
                        reason=f"grid: price dipped to level {level} ({ctx.price:.2f})",
                    )
                )
            elif level > self.last_level and self.last_level in self.owned_levels:
                self.owned_levels.discard(self.last_level)
                self.last_trade_price = ctx.price
                signals.append(
                    TradeSignal(
                        symbol=self.symbol,
                        side="sell",
                        size_fraction=self.order_size_fraction,
                        reason=f"grid: price rose from level {self.last_level} to {level} ({ctx.price:.2f})",
                    )
                )

        self.last_level = level
        return signals
