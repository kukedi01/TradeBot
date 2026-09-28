from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Literal


@dataclass
class TradeSignal:
    symbol: str
    side: Literal["buy", "sell"]
    size_fraction: float
    reason: str


@dataclass
class StrategyContext:
    symbol: str
    price: float
    cash_usd: float
    holdings: dict
    pause_new_entries: bool = False
    size_multiplier: float = 1.0
    # Live: the tick-to-tick delta of Kraken's 24h volume counter (see
    # session/loop.py's _record_chart_tick). Backtest: the OHLCV candle's
    # own volume field. Defaults to 0.0 for strategies/callers that don't
    # care about it -- only trend/momentum currently reads this.
    volume: float = 0.0
    # The position's weighted-average entry price (Portfolio.cost_basis /
    # the backtest engine's own avg_cost tracker), 0.0 if nothing is held.
    # Only grid currently reads this, to avoid selling a level-up bounce
    # that's still below what was actually paid for the whole position.
    cost_basis: float = 0.0
    # Cash plus *every* coin's holdings at current prices -- the only figure
    # a strategy can use to work out what share of the portfolio it holds.
    # `holdings` alone can't answer that: it lists every coin's quantity but
    # `price` is only this symbol's, so there's no way to value the rest.
    # dca_rebalance guessed at it as `held_value + cash_usd`, which treats
    # the shared cash pool as the only other asset and inflated a real 12.5%
    # ETH weight into a reported 81.8% -- see that strategy. 0.0 means the
    # caller didn't supply it, and a strategy must then treat the share as
    # unknown rather than computing a wrong one.
    portfolio_value: float = 0.0
    # Which strategy's buy opened the position currently held on this symbol
    # (session/loop.py's _position_owners, the backtest engines' own
    # equivalents), None if nothing is held or the record was lost. Needed
    # because `holdings` is shared: without it a strategy cannot tell its own
    # position from another strategy's, and trend_momentum read any holding
    # at all as "I am already invested" -- which, with grid holding the coin
    # 95.7-100% of the time, made its entry branch unreachable for a whole
    # 8-day session (0 buys, 12 sells).
    position_owner: str | None = None


class Strategy(ABC):
    name: str

    # Attribute names that are *configuration*, not memory. load_state skips
    # them, so a freshly built instance keeps the value the registry (or
    # Kelly sizing) just gave it instead of having a stale one restored over
    # the top.
    #
    # Without this, a tuning change can never reach a session that is already
    # running: get_state() snapshots every attribute via vars(self), so a
    # parameter edited in the registry is silently overwritten on the next
    # restart by whatever the database remembers. That is not theoretical --
    # raising grid's min_move_pct from 0.3 to 0.85 after a backtest sweep
    # would have applied to new sessions only, while the 17-day live session
    # the sweep was run *for* kept trading on 0.3 indefinitely.
    #
    # Only genuinely independent knobs belong here. Grid's band bounds and
    # step, for instance, look like configuration but are memory: the band
    # recenters itself as price drifts, and step is derived from bounds and
    # grid_levels together, so restoring one without the others would leave
    # the strategy internally inconsistent.
    TUNING_ATTRS: frozenset[str] = frozenset()

    @abstractmethod
    def on_tick(self, ctx: StrategyContext) -> list[TradeSignal]:
        ...

    def on_external_sell(self) -> None:
        """Called when a position gets closed outside this strategy's own
        on_tick logic (e.g. the position-level stop-loss guardrail
        liquidates it). No-op by default; a strategy that tracks "am I in a
        position" internally with state that isn't re-derived from
        ctx.holdings every tick (grid's owned levels) must override this so
        that state doesn't go stale and block/confuse its own future
        signals. A strategy that reads ctx.holdings fresh each tick instead
        (trend/momentum, dca_rebalance) needs no override -- it self-corrects
        automatically the moment holdings actually change."""
        pass

    def on_signal_not_filled(self) -> None:
        """Called when the most recent buy signal this strategy returned
        from on_tick() did NOT result in an actual purchase -- blocked
        because this strategy wasn't the regime-selected active one,
        blocked by a sentiment pause, or shrunk to zero by
        correlation/concentration sizing. No-op by default; a strategy that
        marks itself "in position" at signal time rather than at
        confirmed-fill time (grid adding a level to owned_levels) must
        override this to undo that mark -- otherwise it believes it holds
        something it was never actually able to buy, and permanently
        refuses to reconsider that level/entry even on a genuine future
        opportunity. Prefer deriving "in position" from ctx.holdings each
        tick instead where the strategy's state allows it (see
        TrendMomentumStrategy) -- it needs no such hook at all then."""
        pass

    def get_state(self) -> dict:
        """Generic snapshot of every instance attribute, so a strategy's
        memory (grid levels bought, moving-average history, ...) survives a
        backend restart instead of resetting. `set` and `deque` aren't
        JSON-native, so they're wrapped in a small marker dict on the way
        out and unwrapped again in load_state."""
        state = {}
        for key, value in vars(self).items():
            if isinstance(value, set):
                state[key] = {"__set__": list(value)}
            elif isinstance(value, deque):
                state[key] = {"__deque__": list(value), "maxlen": value.maxlen}
            else:
                state[key] = value
        return state

    def load_state(self, state: dict) -> None:
        for key, value in state.items():
            if key in self.TUNING_ATTRS:
                continue
            if isinstance(value, dict) and "__set__" in value:
                setattr(self, key, set(value["__set__"]))
            elif isinstance(value, dict) and "__deque__" in value:
                setattr(self, key, deque(value["__deque__"], maxlen=value["maxlen"]))
            else:
                setattr(self, key, value)
