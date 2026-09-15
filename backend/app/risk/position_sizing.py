from app.backtest.data_loader import fetch_historical_ohlcv
from app.backtest.engine import run_backtest

# A strategy whose 150-day backtest shows a negative edge gets a raw Kelly
# fraction of exactly 0.0 -- mathematically correct, but live it meant that
# strategy could never place a real order at all. This floor keeps some size
# on the table even for an unproven/losing edge, at the cost of accepting
# more live risk than a strict Kelly gate would. Deliberately higher risk
# tolerance than the pure Kelly math -- raise or lower to taste.
MIN_LIVE_KELLY_FRACTION = 0.08


def live_size_overrides(symbol: str, days: int = 150) -> dict[str, float]:
    """Every strategy's live Kelly-derived order size for one symbol, shaped
    for backtest/engine.py's size_fraction_override parameter -- so a
    backtest can be run with the sizes a live session would actually use
    instead of each strategy's hand-picked default (grid's live 0.8 vs its
    own 0.1 default is an 8x gap, which is most of why "auto" backtests
    looked so much less invested than the real bot).

    Caveat worth keeping in mind: these are computed from the LAST `days`
    days of data, so applying them to a backtest of an older window is a mild
    look-ahead -- the sizes were informed by price action the backtested run
    couldn't have seen yet. Fine for "how would today's bot have done",
    misleading if read as a clean out-of-sample result.
    """
    from app.strategies.registry import STRATEGY_BUILDERS

    return {name: compute_kelly_size_for_strategy(name, symbol, days) for name in STRATEGY_BUILDERS}


def compute_kelly_size_for_strategy(strategy_name: str, symbol: str, days: int = 150) -> float:
    """Runs a fresh backtest for the strategy and returns the Kelly fraction,
    floored at MIN_LIVE_KELLY_FRACTION -- used to size live paper-trading
    orders instead of each strategy's fixed default, so a strategy with a
    strong proven edge sizes up while one with a weak or negative edge still
    trades small rather than being fully shut out."""
    candles = fetch_historical_ohlcv(symbol, days=days)
    result = run_backtest(strategy_name, symbol, candles)
    raw = kelly_fraction(result["win_pnls"], result["loss_pnls"])["kelly_fraction"]
    return max(raw, MIN_LIVE_KELLY_FRACTION)


def kelly_fraction(win_pnls: list[float], loss_pnls: list[float], max_fraction: float = 0.8) -> dict:
    """Simplified Kelly criterion: how much of the bankroll to risk per trade,
    given the strategy's own historical win rate and average win/loss size.

    We use HALF the full Kelly number (a common, more conservative practice)
    and cap it at max_fraction, since the full Kelly formula assumes we know
    the true win rate exactly -- in reality it's just an estimate from a
    limited backtest, and overbetting on a noisy estimate is a fast way to
    blow up an account. max_fraction was raised from an initial 0.5 to 0.8
    after a trend_momentum position-size sweep backtest (0.2 through 1.0)
    showed every tradable coin's max drawdown staying under the 12% position
    stop-loss up to roughly 0.8 -- still paper trading, so the appetite for
    a bigger, still-backtest-checked position size is deliberately higher
    than a live-money Kelly gate would normally allow.
    """
    total_trades = len(win_pnls) + len(loss_pnls)
    if total_trades == 0:
        return {"win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "reward_risk_ratio": 0.0, "kelly_fraction": 0.0}

    win_rate = len(win_pnls) / total_trades
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
    avg_loss = abs(sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0.0

    if not loss_pnls or avg_loss == 0:
        # No losing trades recorded yet, so we can't compute a reward:risk
        # ratio -- but a clean track record still warrants capping at the
        # safety limit rather than reporting "no edge" as a plain 0/0 would.
        return {
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "reward_risk_ratio": 0.0,
            "kelly_fraction": max_fraction if win_pnls else 0.0,
        }

    if avg_win == 0:
        # Only losses recorded, zero wins -- there's no edge to size up on
        # (and reward_risk_ratio would otherwise be a division by zero).
        return {
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "reward_risk_ratio": 0.0,
            "kelly_fraction": 0.0,
        }

    reward_risk_ratio = avg_win / avg_loss
    loss_rate = 1 - win_rate
    full_kelly = win_rate - (loss_rate / reward_risk_ratio)
    half_kelly = full_kelly / 2

    return {
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "reward_risk_ratio": reward_risk_ratio,
        "kelly_fraction": max(0.0, min(half_kelly, max_fraction)),
    }
