from app.risk.guardrails import (
    MAX_ASSET_ALLOCATION_PCT,
    STOP_LOSS_PCT,
    check_drawdown_limit,
    check_position_stop_loss,
    concentration_size_multiplier,
)


class TestDrawdownLimit:
    def test_no_breach_within_limit(self):
        result = check_drawdown_limit(current_value_eur=950.0, past_values_eur=[1000.0], max_drawdown_pct=20.0)
        assert result.breached is False
        assert result.peak_value_eur == 1000.0
        assert round(result.drawdown_pct, 2) == 5.0

    def test_breach_past_limit(self):
        result = check_drawdown_limit(current_value_eur=750.0, past_values_eur=[1000.0, 900.0], max_drawdown_pct=20.0)
        assert result.breached is True
        assert result.drawdown_pct == 25.0

    def test_none_limit_never_breaches(self):
        result = check_drawdown_limit(current_value_eur=1.0, past_values_eur=[1000.0], max_drawdown_pct=None)
        assert result.breached is False

    def test_peak_considers_current_value_too(self):
        # A new all-time-high tick should itself become the peak, not be
        # compared against a stale past peak.
        result = check_drawdown_limit(current_value_eur=1200.0, past_values_eur=[1000.0], max_drawdown_pct=20.0)
        assert result.peak_value_eur == 1200.0
        assert result.drawdown_pct == 0.0


class TestPositionStopLoss:
    def test_triggers_at_threshold(self):
        avg_cost = 100.0
        current_price = avg_cost * (1 - STOP_LOSS_PCT / 100)
        result = check_position_stop_loss(current_price, avg_cost)
        assert result.triggered is True

    def test_does_not_trigger_below_threshold(self):
        result = check_position_stop_loss(current_price=95.0, avg_cost=100.0)
        assert result.triggered is False
        assert round(result.loss_pct, 2) == 5.0

    def test_price_above_cost_never_triggers(self):
        result = check_position_stop_loss(current_price=110.0, avg_cost=100.0)
        assert result.triggered is False

    def test_zero_avg_cost_is_treated_as_no_position(self):
        result = check_position_stop_loss(current_price=1.0, avg_cost=0.0)
        assert result.triggered is False


class TestConcentrationLimit:
    def test_buy_within_cap_is_unrestricted(self):
        prices = {"BTC/EUR": 100.0}
        multiplier = concentration_size_multiplier("BTC/EUR", 0.3, cash_usd=1000.0, holdings={}, prices=prices)
        assert multiplier == 1.0

    def test_buy_exceeding_cap_is_shrunk_to_the_boundary(self):
        prices = {"BTC/EUR": 100.0}
        # 50% of 1000 cash = 500 EUR spend against a 1000 EUR total
        # portfolio (50%) breaches the 40% cap -- should shrink to exactly
        # the 400 EUR headroom.
        multiplier = concentration_size_multiplier("BTC/EUR", 0.5, cash_usd=1000.0, holdings={}, prices=prices)
        assert round(multiplier, 3) == round(0.4 / 0.5, 3)

    def test_already_at_cap_blocks_entirely(self):
        prices = {"BTC/EUR": 100.0}
        # Already holding exactly the cap's worth of BTC -- no headroom left.
        btc_value = 1000.0 * MAX_ASSET_ALLOCATION_PCT / 100
        holdings = {"BTC": btc_value / 100.0}
        multiplier = concentration_size_multiplier(
            "BTC/EUR", 0.2, cash_usd=1000.0 - btc_value, holdings=holdings, prices=prices
        )
        assert multiplier == 0.0

    def test_zero_total_portfolio_value_is_unrestricted(self):
        multiplier = concentration_size_multiplier("BTC/EUR", 0.5, cash_usd=0.0, holdings={}, prices={"BTC/EUR": 100.0})
        assert multiplier == 1.0
