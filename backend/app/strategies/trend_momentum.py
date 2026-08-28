from collections import deque

from app.strategies.base import Strategy, StrategyContext, TradeSignal
from app.strategies.indicators import bollinger_bands, macd_series, rsi, sma


class TrendMomentumStrategy(Strategy):
    """Buys on a golden cross (fast moving average above slow), confirmed by
    price trading above its own Bollinger middle band, MACD agreeing
    (MACD line above its own signal line -- separate momentum confirmation
    from a different indicator family, not just the same SMA cross read
    twice), and above-average volume (a cross on quiet trading is more
    likely noise than genuine participation). Sells on a death cross, or
    when price closes back below the middle band (the trend has actually
    broken) -- not just because RSI got high, which a strong trend can stay
    at for a long time while still going up. MACD/volume are entry filters
    only; the exit stays as permissive as before, since delaying a real
    exit behind extra confirmation is a worse trade-off than an occasional
    unconfirmed one.

    A cross only counts once fast and slow have actually separated by
    min_cross_gap_pct -- without this, a fast/slow pair sitting almost
    exactly on top of each other in a choppy market flips "golden"/"death"
    on essentially rounding noise, buying and selling within minutes and
    losing the round-trip to fees every time. Same fix pattern as grid's
    min_move_pct hysteresis, applied to the cross instead of a price level.

    "Am I in a position" is read fresh from ctx.holdings every tick rather
    than cached on self -- a cached flag can only be set speculatively (at
    signal time, before the trade is known to have actually filled) and
    desync from the real portfolio if that signal gets blocked or shrunk to
    zero, which is exactly what left this strategy stuck retrying a sell of
    a position it never actually held, every tick, indefinitely.
    """

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
        min_cross_gap_pct: float = 0.15,
        volume_confirmation_multiplier: float = 1.0,
    ):
        self.symbol = symbol
        self.fast_ma_period = fast_ma_period
        self.slow_ma_period = slow_ma_period
        self.rsi_period = rsi_period
        self.rsi_extreme_overbought = rsi_extreme_overbought
        self.bollinger_period = bollinger_period
        self.order_size_fraction = order_size_fraction
        self.min_cross_gap_pct = min_cross_gap_pct
        self.volume_confirmation_multiplier = volume_confirmation_multiplier
        self.price_history: deque[float] = deque(maxlen=history_size)
        self.volume_history: deque[float] = deque(maxlen=history_size)

    def on_tick(self, ctx: StrategyContext) -> list[TradeSignal]:
        self.price_history.append(ctx.price)
        self.volume_history.append(ctx.volume)
        prices = list(self.price_history)

        fast = sma(prices, self.fast_ma_period)
        slow = sma(prices, self.slow_ma_period)
        current_rsi = rsi(prices, self.rsi_period)
        _, middle_band, _ = bollinger_bands(prices, self.bollinger_period)

        if fast is None or slow is None or current_rsi is None or middle_band is None:
            return []

        base_asset = self.symbol.split("/")[0]
        in_position = ctx.holdings.get(base_asset, 0) > 0

        cross_gap_pct = abs(fast - slow) / slow * 100 if slow else 0.0
        golden_cross = fast > slow and cross_gap_pct >= self.min_cross_gap_pct
        above_middle_band = ctx.price > middle_band
        not_blow_off_top = current_rsi < self.rsi_extreme_overbought

        macd_line, macd_signal_line, _ = macd_series(prices)
        macd_confirmed = (
            macd_line[-1] is not None and macd_signal_line[-1] is not None and macd_line[-1] > macd_signal_line[-1]
        )

        volumes = list(self.volume_history)
        avg_volume = sum(volumes) / len(volumes) if volumes else 0.0
        # avg_volume > 0 also acts as "wait until real volume data has
        # accumulated" -- a fresh strategy instance starts with a 0.0
        # reading (no prior tick to diff against), which would otherwise
        # read as "any nonzero volume confirms."
        volume_confirmed = avg_volume > 0 and ctx.volume >= avg_volume * self.volume_confirmation_multiplier

        if (
            golden_cross
            and above_middle_band
            and not_blow_off_top
            and macd_confirmed
            and volume_confirmed
            and not in_position
        ):
            return [
                TradeSignal(
                    symbol=self.symbol,
                    side="buy",
                    size_fraction=self.order_size_fraction,
                    reason=(
                        f"trend_momentum: golden cross (fast {fast:.2f} > slow {slow:.2f}), "
                        f"price above Bollinger middle band ({middle_band:.2f}), MACD confirmed, "
                        f"volume {ctx.volume:.2f} >= avg {avg_volume:.2f}"
                    ),
                )
            ]

        death_cross = fast < slow and cross_gap_pct >= self.min_cross_gap_pct
        trend_broken = ctx.price < middle_band

        if (death_cross or trend_broken) and in_position:
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
