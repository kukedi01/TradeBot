import random


def run_monte_carlo(equity_curve: list[float], num_simulations: int = 1000, confidence: float = 0.95) -> dict:
    """Bootstraps the strategy's own historical period-over-period returns to
    simulate many alternative equity paths, then reads off the probability
    and severity of large losses from those simulations -- rather than
    assuming returns follow a neat statistical distribution, which real
    market returns famously don't (fat tails, sudden crashes)."""
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] != 0
    ]

    if not returns:
        return {
            "simulations": 0,
            "confidence": confidence,
            "var_pct": 0.0,
            "cvar_pct": 0.0,
            "prob_loss_10pct": 0.0,
            "prob_loss_25pct": 0.0,
            "prob_loss_50pct": 0.0,
        }

    num_periods = len(returns)
    final_returns = []

    for _ in range(num_simulations):
        equity = 1.0
        for _ in range(num_periods):
            equity *= 1 + random.choice(returns)
        final_returns.append((equity - 1) * 100)

    final_returns.sort()

    var_index = int((1 - confidence) * num_simulations)
    var_pct = final_returns[var_index]
    tail_losses = final_returns[: var_index + 1]
    cvar_pct = sum(tail_losses) / len(tail_losses) if tail_losses else var_pct

    return {
        "simulations": num_simulations,
        "confidence": confidence,
        "var_pct": var_pct,
        "cvar_pct": cvar_pct,
        "prob_loss_10pct": sum(1 for r in final_returns if r <= -10) / num_simulations * 100,
        "prob_loss_25pct": sum(1 for r in final_returns if r <= -25) / num_simulations * 100,
        "prob_loss_50pct": sum(1 for r in final_returns if r <= -50) / num_simulations * 100,
    }
