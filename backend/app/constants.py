# Coins a session spreads its shared cash pool across -- which one reaches
# the goal doesn't matter. Lives here (rather than in session/loop.py, where
# it originated) so both the live loop and the backtest engine can import it
# without creating a circular import between them.
TRADABLE_SYMBOLS = ["BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR"]

# A regime-flip handoff sell (the newly active strategy closing a position it
# didn't open) must clear the position's *original* owner's cost basis by at
# least this margin -- same reasoning as grid's own min_profit_margin_pct:
# a raw price a hair above cost basis still nets a real loss once the sell
# fee/slippage is applied. Lives here (not session/loop.py, where it
# originated) so the backtest engine can share it without a circular import
# (session/loop.py already depends on backtest/engine.py indirectly through
# risk/position_sizing.py's Kelly sizing).
HANDOFF_MIN_PROFIT_MARGIN_PCT = 1.0
