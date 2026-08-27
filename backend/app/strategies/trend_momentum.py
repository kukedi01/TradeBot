from collections import deque

from app.strategies.base import Strategy, StrategyContext, TradeSignal
from app.strategies.indicators import bollinger_bands, rsi, sma


class TrendMomentumStrategy(Strategy):
    """Buys on a golden cross (fast moving average above slow), confirmed by
    price trading above its own Bollinger middle band. Sells on a death
    cross, or when price closes back below the middle band (the trend has
    actually broken) -- not just because RSI got high, which a strong trend
    can stay at for a long time while still going up."""

    name = "trend_momentum"

    def __init__(
        self,
        symbol: str,
        fast_ma_period: int = 5,
        slow_ma_period: int = 20,
        rsi_period: int = 14,
        rsi_extreme_overbought: float = 85,
        bollinger_period: int = 20,
        order_size_fraction: float = 0.2,
        history_size: int = 50,
    ):
        self.symbol = symbol
        self.fast_ma_period = fast_ma_period
        self.slow_ma_period = slow_ma_period
        self.rsi_period = rsi_period
        self.rsi_extreme_overbought = rsi_extreme_overbought
        self.bollinger_period = bollinger_period
        self.order_size_fraction = order_size_fraction
        self.price_history: deque[float] = deque(maxlen=history_size)
        self.in_position = False
        # Set right before returning a buy/sell signal, so on_signal_not_filled
        # can undo the speculative in_position flip if the signal never
        # actually results in a fill (see that method).
        self._pending_previous_in_position: bool | None = None

    def on_tick(self, ctx: StrategyContext) -> list[TradeSignal]:
        self.price_history.append(ctx.price)
        prices = list(self.price_history)

        fast = sma(prices, self.fast_ma_period)
        slow = sma(prices, self.slow_ma_period)
        current_rsi = rsi(prices, self.rsi_period)
        _, middle_band, _ = bollinger_bands(prices, self.bollinger_period)

        if fast is None or slow is None or current_rsi is None or middle_band is None:
            return []

        golden_cross = fast > slow
        above_middle_band = ctx.price > middle_band
        not_blow_off_top = current_rsi < self.rsi_extreme_overbought

        if golden_cross and above_middle_band and not_blow_off_top and not self.in_position:
            self._pending_previous_in_position = self.in_position
            self.in_position = True
            return [
                TradeSignal(
                    symbol=self.symbol,
                    side="buy",
                    size_fraction=self.order_size_fraction,
                    reason=f"trend_momentum: golden cross (fast {fast:.2f} > slow {slow:.2f}), price above Bollinger middle band ({middle_band:.2f})",
                )
            ]

        death_cross = fast < slow
        trend_broken = ctx.price < middle_band

        if (death_cross or trend_broken) and self.in_position:
            self._pending_previous_in_position = self.in_position
            self.in_position = False
            reason = "death cross" if death_cross else f"price fell below Bollinger middle band ({middle_band:.2f})"
            return [
                TradeSignal(
                    symbol=self.symbol,
                    side="sell",
                    size_fraction=1.0,
                    reason=f"trend_momentum: {reason} (fast {fast:.2f}, slow {slow:.2f})",
                )
            ]

        return []

    def on_external_sell(self) -> None:
        # A stop-loss liquidation outside this strategy's own logic still
        # closes the position -- without this, in_position would stay True
        # until a death cross or band break happens to occur too, blocking
        # any new buy signal in the meantime even though nothing is held.
        self.in_position = False

    def on_signal_not_filled(self) -> None:
        # The buy/sell this tick's on_tick() just returned never actually
        # went through -- undo the speculative in_position flip made when
        # the signal was created, or this strategy believes it holds (or
        # doesn't hold) a position that was never actually opened/closed.
        if self._pending_previous_in_position is None:
            return
        self.in_position = self._pending_previous_in_position
        self._pending_previous_in_position = None
