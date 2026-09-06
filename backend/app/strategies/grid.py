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

    A "sell" only fires once price actually clears the position's blended
    average cost by min_profit_margin_pct -- not just once price rises one
    level above the last trade. Without this, averaging down through
    several dips and then selling on a modest bounce ("price rose a level")
    can still realize a loss, because the bounce only has to beat the *last*
    buy's level, not the *average* of every buy that's still open. A
    150-day backtest showed exactly this: ~50% nominal win rate, but average
    losses 2-4x the size of average wins on every one of the 4 tradable
    coins, because most "wins" were tiny one-level bounces while "losses"
    were the accumulated cost of several averaged-down buys sold below
    their blended cost. The 12%/max-drawdown guardrails remain the only
    sanctioned way to realize an actual loss; grid's own logic should only
    ever sell for a real profit or hold.
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
        min_profit_margin_pct: float = 1.0,
    ):
        self.symbol = symbol
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.grid_levels = grid_levels
        self.step = (upper_bound - lower_bound) / grid_levels
        self.order_size_fraction = order_size_fraction
        self.recenter_after_ticks_out_of_range = recenter_after_ticks_out_of_range
        self.min_move_pct = min_move_pct
        self.min_profit_margin_pct = min_profit_margin_pct
        self.owned_levels: set[int] = set()
        self.last_level: int | None = None
        # Seeded to the band's own center (== the price the strategy was
        # built at), not None -- otherwise the very first trade a fresh
        # instance ever makes has zero hysteresis protection (see
        # _far_enough_from_last_trade, which only guards trade-to-trade
        # moves), so a level boundary sitting a few EUR from the starting
        # price could fire an immediate "dip" buy on pure tick noise, not a
        # real dip. Seeding here makes the first trade clear the same
        # min_move_pct bar as every later one.
        self.last_trade_price: float | None = (lower_bound + upper_bound) / 2
        self.ticks_out_of_range = 0
        # Set right before returning a buy/sell signal, so on_signal_not_filled
        # can undo the speculative owned_levels/last_trade_price mutation if
        # the signal never actually results in a fill (see that method).
        self._pending_signal: dict | None = None

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
            previous_trade_price = self.last_trade_price
            if level < self.last_level and level not in self.owned_levels:
                self.owned_levels.add(level)
                self.last_trade_price = ctx.price
                self._pending_signal = {"side": "buy", "level": level, "previous_trade_price": previous_trade_price}
                signals.append(
                    TradeSignal(
                        symbol=self.symbol,
                        side="buy",
                        size_fraction=self.order_size_fraction,
                        reason=f"grid: price dipped to level {level} ({ctx.price:.2f})",
                    )
                )
            elif level > self.last_level and self.last_level in self.owned_levels:
                if ctx.cost_basis > 0 and ctx.price < ctx.cost_basis * (1 + self.min_profit_margin_pct / 100):
                    # Price rose a level, but not enough to clear the
                    # blended average cost of the whole position (e.g.
                    # after averaging down through several dips) --
                    # selling here would realize a loss dressed up as a
                    # "level rose" win. Hold, and leave last_level pinned
                    # at the still-owned level so a further rise keeps
                    # getting checked against it, instead of losing track.
                    return signals
                self.owned_levels.discard(self.last_level)
                self.last_trade_price = ctx.price
                self._pending_signal = {
                    "side": "sell",
                    "level": self.last_level,
                    "previous_trade_price": previous_trade_price,
                }
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

    def on_external_sell(self) -> None:
        # A stop-loss liquidation outside this strategy's own logic means
        # every level it thought it owned is no longer actually held --
        # otherwise it would refuse to re-buy a dip at a level it still
        # (incorrectly) believes it's holding.
        self.owned_levels = set()

    def on_signal_not_filled(self) -> None:
        # The buy/sell this tick's on_tick() just returned never actually
        # went through (blocked as inactive strategy, blocked by sentiment,
        # or shrunk to zero) -- undo the owned_levels/last_trade_price
        # mutation made when the signal was created, or this level stays
        # permanently (and wrongly) marked as bought/sold.
        if self._pending_signal is None:
            return
        level = self._pending_signal["level"]
        if self._pending_signal["side"] == "buy":
            self.owned_levels.discard(level)
        else:
            self.owned_levels.add(level)
        self.last_trade_price = self._pending_signal["previous_trade_price"]
        self._pending_signal = None
