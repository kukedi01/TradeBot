"""The rebalance side of dca_rebalance: does it measure this coin's share of
the portfolio correctly?

It used to measure `held_value / (held_value + cash)`, treating the shared
cash pool as the only other asset. In a four-coin session that inflated a
real 12.5% ETH weight into a reported 81.8%, so the strategy fired a
rebalance sell on three coins out of four -- 424 sell signals against 113
scheduled buys on one live session. Nothing moved (every one was blocked
downstream by the ownership gate), but the number driving them was
meaningless.
"""

from app.strategies.base import StrategyContext
from app.strategies.dca_rebalance import DcaRebalanceStrategy

SYMBOL = "ETH/EUR"
PRICE = 2000.0


def context(held_qty: float, cash: float, portfolio_value: float) -> StrategyContext:
    return StrategyContext(
        symbol=SYMBOL,
        price=PRICE,
        cash_usd=cash,
        holdings={"ETH": held_qty},
        portfolio_value=portfolio_value,
    )


def sells(signals) -> list:
    return [s for s in signals if s.side == "sell"]


class TestRebalanceAllocation:
    def test_a_small_real_share_does_not_trigger_a_rebalance(self):
        """The live case that exposed the bug: ETH worth 125 EUR in a 1000
        EUR portfolio is 12.5%, nowhere near the 50% target -- but with only
        27.82 EUR of shared cash on hand the old math read it as 81.8% and
        sold."""
        strategy = DcaRebalanceStrategy(symbol=SYMBOL)
        ctx = context(held_qty=0.0625, cash=27.82, portfolio_value=1000.0)

        assert sells(strategy.on_tick(ctx)) == []

    def test_a_genuinely_oversized_position_still_rebalances(self):
        """The feature itself must keep working: 70% of the portfolio is
        past the 50% target plus the 10% drift allowance."""
        strategy = DcaRebalanceStrategy(symbol=SYMBOL)
        ctx = context(held_qty=0.35, cash=300.0, portfolio_value=1000.0)

        assert len(sells(strategy.on_tick(ctx))) == 1

    def test_an_unknown_portfolio_value_never_rebalances(self):
        """0.0 means the caller didn't supply one. Guessing a share from the
        cash pool alone is what caused the bug, so the strategy holds instead
        -- not selling is the recoverable direction to be wrong."""
        strategy = DcaRebalanceStrategy(symbol=SYMBOL)
        ctx = context(held_qty=0.35, cash=300.0, portfolio_value=0.0)

        assert sells(strategy.on_tick(ctx)) == []

    def test_scheduled_buys_are_unaffected_by_the_allocation_reading(self):
        """The DCA half of the strategy is a schedule, not an allocation
        judgement -- it must still fire on its interval."""
        strategy = DcaRebalanceStrategy(symbol=SYMBOL, dca_interval_ticks=3)
        ctx = context(held_qty=0.0625, cash=500.0, portfolio_value=1000.0)

        sides = [signal.side for _ in range(3) for signal in strategy.on_tick(ctx)]

        assert sides == ["buy"]
