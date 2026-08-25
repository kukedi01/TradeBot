def compute_metrics(result: dict) -> dict:
    starting = result["starting_balance_usd"]
    equity_curve = result["equity_curve"]
    win_pnls = result["win_pnls"]
    loss_pnls = result["loss_pnls"]

    if not equity_curve:
        return {
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "win_rate_pct": 0.0,
            "volatility": 0.0,
            "sharpe_like_ratio": 0.0,
            "trade_count": 0,
        }

    ending = equity_curve[-1]
    total_return_pct = (ending - starting) / starting * 100

    peak = equity_curve[0]
    max_drawdown_pct = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak * 100)

    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] != 0
    ]
    if returns:
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        volatility = variance**0.5
        sharpe_like_ratio = mean_return / volatility if volatility > 0 else 0.0
    else:
        volatility = 0.0
        sharpe_like_ratio = 0.0

    total_closed_trades = len(win_pnls) + len(loss_pnls)
    win_rate_pct = (len(win_pnls) / total_closed_trades * 100) if total_closed_trades > 0 else 0.0

    return {
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate_pct": win_rate_pct,
        "volatility": volatility,
        "sharpe_like_ratio": sharpe_like_ratio,
        "trade_count": len(result["trades"]),
    }
