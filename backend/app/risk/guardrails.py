from dataclasses import dataclass


@dataclass
class RiskCheckResult:
    breached: bool
    peak_value_eur: float
    drawdown_pct: float


def check_drawdown_limit(
    current_value_eur: float,
    past_values_eur: list[float],
    max_drawdown_pct: float | None,
) -> RiskCheckResult:
    """Independent of any strategy: compares the portfolio's current value
    against the highest value it has ever reached in this session. If it has
    fallen more than max_drawdown_pct below that peak, the session should
    stop -- regardless of what the active strategy thinks it's doing."""
    peak_value_eur = max([current_value_eur, *past_values_eur])
    drawdown_pct = (peak_value_eur - current_value_eur) / peak_value_eur * 100 if peak_value_eur > 0 else 0.0

    breached = max_drawdown_pct is not None and drawdown_pct >= max_drawdown_pct
    return RiskCheckResult(breached=breached, peak_value_eur=peak_value_eur, drawdown_pct=drawdown_pct)
