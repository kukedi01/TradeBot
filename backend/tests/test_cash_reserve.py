"""The cash-reserve sizing multiplier.

Currently disabled in production (MIN_CASH_RESERVE_PCT is 0.0) because a
sweep found it trades ~1pp of return for lower drawdown -- see the constant's
comment. Tested anyway: it is wired into both the live loop and the
multi-coin backtest engine, so if it is ever switched on it must already
behave identically on both sides rather than being debugged live.
"""

from app.risk.guardrails import cash_reserve_size_multiplier


class TestCashReserve:
    def test_disabled_by_default_never_shrinks_anything(self):
        """The shipped configuration must be a true no-op, not an
        almost-no-op -- every live buy passes through this call."""
        assert cash_reserve_size_multiplier(1.0, cash_usd=500.0, portfolio_value=1000.0) == 1.0

    def test_a_buy_that_stays_above_the_floor_is_untouched(self):
        # 300 cash in a 1000 portfolio, 10% floor = 100 reserved. Spending
        # 50% of cash is 150, well inside the 200 that is free.
        assert cash_reserve_size_multiplier(0.5, cash_usd=300.0, portfolio_value=1000.0, reserve_pct=10.0) == 1.0

    def test_a_buy_that_would_breach_the_floor_is_trimmed_to_it(self):
        # 300 cash, 200 reserved (20% of 1000) -> only 100 spendable, but the
        # signal wants 300. The multiplier must scale it to exactly 100.
        multiplier = cash_reserve_size_multiplier(1.0, cash_usd=300.0, portfolio_value=1000.0, reserve_pct=20.0)
        assert multiplier == 100.0 / 300.0

    def test_no_buy_at_all_once_cash_is_already_at_or_below_the_floor(self):
        assert cash_reserve_size_multiplier(0.5, cash_usd=100.0, portfolio_value=1000.0, reserve_pct=10.0) == 0.0
        assert cash_reserve_size_multiplier(0.5, cash_usd=50.0, portfolio_value=1000.0, reserve_pct=10.0) == 0.0

    def test_an_unknown_portfolio_value_does_not_block_trading(self):
        """0.0 means the caller couldn't value the book. Refusing every buy on
        a missing input would silently halt the bot; the other sizing
        multipliers degrade open the same way."""
        assert cash_reserve_size_multiplier(0.5, cash_usd=300.0, portfolio_value=0.0, reserve_pct=20.0) == 1.0
