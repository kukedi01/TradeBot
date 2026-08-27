# Coins a session spreads its shared cash pool across -- which one reaches
# the goal doesn't matter. Lives here (rather than in session/loop.py, where
# it originated) so both the live loop and the backtest engine can import it
# without creating a circular import between them.
TRADABLE_SYMBOLS = ["BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR"]
