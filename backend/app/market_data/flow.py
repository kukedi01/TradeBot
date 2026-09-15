"""Order-flow metrics that plain OHLCV candles can't express: cumulative
volume delta (who is trading aggressively, buyers or sellers) and open
interest (how much derivative exposure is actually open).

Neither is wired into any trading decision. They are collected only, because
neither can be backtested from the data Kraken serves: OHLCV candles carry
no buy/sell split, Kraken's public trade history doesn't reach back far
enough to reconstruct months of CVD, and open interest has no historical
endpoint at all (`fetchOpenInterestHistory` is False for both the spot and
futures clients). Acting on either today would mean shipping an unmeasured
signal -- which this project has now watched fail three times in one sitting
(S/R grid levels, Fibonacci entries, RSI divergence exits all looked
plausible and all lost money under measurement). So instead we build the
dataset first and only test hypotheses once there's enough of it.
"""
import ccxt

from app.market_data.kraken_client import kraken

# Kraken's spot API has no open-interest concept; only the futures venue
# does, and only as a live reading (no history), so the value is sampled
# rather than fetched retrospectively.
_futures = ccxt.krakenfutures({"timeout": 15000})

# Open interest moves on the scale of hours, not the 30s trading tick, and
# one call returns every contract at once -- so it's fetched on its own
# cadence and shared, the same way the correlation matrix is.
OPEN_INTEREST_CACHE_SECONDS = 300
_oi_cache: dict[str, float] = {}
_oi_cache_at: float = 0.0

# Highest trade id already counted per symbol, so a poll that overlaps the
# previous one (Kraken's `since` is inclusive and trades can share a
# millisecond) doesn't double-count the same fills into the delta.
_last_trade_id: dict[str, str] = {}


def get_volume_delta(symbol: str, limit: int = 500) -> tuple[float, int]:
    """(buy volume - sell volume, trades counted) since the last call for
    this symbol, in base-currency units.

    This is the raw input to cumulative volume delta. Each Kraken trade
    carries the aggressor's side, so a positive delta means buyers were the
    ones crossing the spread -- genuinely different information from total
    volume, which counts both sides of every fill identically and so can
    look identical whether a move was bought up or sold into.

    The first call for a symbol establishes the baseline and returns
    (0.0, 0): with no previous id there's no way to tell which of the
    returned trades are new, and counting all of them would book a large
    fictitious delta the moment the backend starts.
    """
    trades = kraken.fetch_trades(symbol, limit=limit)
    if not trades:
        return 0.0, 0

    previous_id = _last_trade_id.get(symbol)
    _last_trade_id[symbol] = trades[-1]["id"]
    if previous_id is None:
        return 0.0, 0

    new_trades = []
    for trade in reversed(trades):
        if trade["id"] == previous_id:
            break
        new_trades.append(trade)

    delta = 0.0
    for trade in new_trades:
        amount = trade.get("amount") or 0.0
        delta += amount if trade.get("side") == "buy" else -amount
    return delta, len(new_trades)


def _perp_candidates(symbol: str) -> list[str]:
    """This coin's perpetual futures contracts, most preferred first. The
    coins here trade against EUR on spot but only against USD on the futures
    venue, so open interest is necessarily a cross-market reading -- it
    describes positioning in the same asset, not in the exact pair traded.

    Kraken lists two perp flavours per coin, and picking the wrong one is
    not a rounding error: XRP's coin-margined contract reports 1,139 open
    against 10,269,092 on the USD-margined one, and SOL has no coin-margined
    perp at all. The USD-margined contract is preferred because all four
    tradable coins have one, so the series stays comparable.

    The order is fixed rather than "whichever currently has more open
    interest": the two contracts quote open interest in different units
    (coin vs USD notional), so letting the choice drift between samples
    would corrupt the very time series this is being collected for.
    """
    base = symbol.split("/")[0]
    return [f"{base}/USD:USD", f"{base}/USD:{base}"]


def get_open_interest(symbol: str) -> float | None:
    """Open interest on this coin's perpetual contract, or None if the
    futures venue doesn't list it or can't be reached. Cached, see
    OPEN_INTEREST_CACHE_SECONDS."""
    global _oi_cache, _oi_cache_at

    now = _futures.milliseconds() / 1000
    if not _oi_cache or now - _oi_cache_at > OPEN_INTEREST_CACHE_SECONDS:
        tickers = _futures.fetch_tickers()
        refreshed = {}
        for ticker_symbol, ticker in tickers.items():
            open_interest = (ticker.get("info") or {}).get("openInterest")
            if open_interest is not None:
                refreshed[ticker_symbol] = float(open_interest)
        _oi_cache = refreshed
        _oi_cache_at = now

    for candidate in _perp_candidates(symbol):
        if candidate in _oi_cache:
            return _oi_cache[candidate]
    return None
