from app.execution.fill_simulator import SLIPPAGE_BPS, TAKER_FEE_RATE, simulate_fill


def test_buy_applies_positive_slippage_and_deducts_fee_from_spend():
    fill_price, qty, fee = simulate_fill(market_price=100.0, side="buy", size_fraction=0.5, cash_usd=1000.0, held_qty=0.0)

    expected_fill_price = 100.0 * (1 + SLIPPAGE_BPS / 10000)
    assert fill_price == expected_fill_price

    spend = 1000.0 * 0.5
    expected_fee = spend * TAKER_FEE_RATE
    assert fee == expected_fee
    assert qty == (spend - expected_fee) / expected_fill_price


def test_sell_applies_negative_slippage_and_fee_on_proceeds():
    fill_price, qty, fee = simulate_fill(market_price=100.0, side="sell", size_fraction=0.5, cash_usd=0.0, held_qty=10.0)

    expected_fill_price = 100.0 * (1 - SLIPPAGE_BPS / 10000)
    assert fill_price == expected_fill_price
    assert qty == 5.0
    assert fee == qty * expected_fill_price * TAKER_FEE_RATE


def test_zero_size_fraction_yields_zero_quantity():
    _, qty, _ = simulate_fill(market_price=100.0, side="buy", size_fraction=0.0, cash_usd=1000.0, held_qty=0.0)
    assert qty == 0.0


def test_full_sell_liquidates_entire_holding():
    _, qty, _ = simulate_fill(market_price=50.0, side="sell", size_fraction=1.0, cash_usd=0.0, held_qty=3.0)
    assert qty == 3.0
