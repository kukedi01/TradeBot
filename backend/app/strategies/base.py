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


class Strategy(ABC):
    name: str

    @abstractmethod
    def on_tick(self, ctx: StrategyContext) -> list[TradeSignal]:
        ...

    def on_external_sell(self) -> None:
        """Called when a position gets closed outside this strategy's own
        on_tick logic (e.g. the position-level stop-loss guardrail
        liquidates it). No-op by default; a strategy that tracks "am I in a
        position" internally (grid's owned levels, trend/momentum's
        in_position flag) must override this so that state doesn't go stale
        and block/confuse its own future signals."""
        pass

    def on_signal_not_filled(self) -> None:
        """Called when the most recent buy signal this strategy returned
        from on_tick() did NOT result in an actual purchase -- blocked
        because this strategy wasn't the regime-selected active one,
        blocked by a sentiment pause, or shrunk to zero by
        correlation/concentration sizing. No-op by default; a strategy that
        marks itself "in position" (grid adding a level to owned_levels,
        trend/momentum setting in_position) at signal time rather than at
        confirmed-fill time must override this to undo that mark --
        otherwise it believes it holds something it was never actually
        able to buy, and permanently refuses to reconsider that level/entry
        even on a genuine future opportunity."""
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
            if isinstance(value, dict) and "__set__" in value:
                setattr(self, key, set(value["__set__"]))
            elif isinstance(value, dict) and "__deque__" in value:
                setattr(self, key, deque(value["__deque__"], maxlen=value["maxlen"]))
            else:
                setattr(self, key, value)
