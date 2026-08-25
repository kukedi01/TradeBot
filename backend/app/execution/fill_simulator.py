TAKER_FEE_RATE = 0.0026
SLIPPAGE_BPS = 5


def simulate_fill(market_price: float, side: str, size_fraction: float, cash_usd: float, held_qty: float):
    """Returns (fill_price, qty, fee) for a simulated market order.

    Shared by the live PaperExecutor and the backtest engine so both use the
    exact same fee/slippage math.
    """
    slippage_multiplier = 1 + (SLIPPAGE_BPS / 10000) * (1 if side == "buy" else -1)
    fill_price = market_price * slippage_multiplier

    if side == "buy":
        spend_usd = cash_usd * size_fraction
        fee = spend_usd * TAKER_FEE_RATE
        qty = (spend_usd - fee) / fill_price
    else:
        qty = held_qty * size_fraction
        proceeds_usd = qty * fill_price
        fee = proceeds_usd * TAKER_FEE_RATE

    return fill_price, qty, fee
