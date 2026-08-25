from sqlalchemy.orm import Session as DbSession

from app.db.models import StrategyPerformanceRecord
from app.risk.profiles import RISK_BANDS


def recommend_strategy(db: DbSession, risk_level: str, symbol: str) -> dict:
    band = RISK_BANDS[risk_level]

    records = (
        db.query(StrategyPerformanceRecord)
        .filter(StrategyPerformanceRecord.symbol == symbol)
        .order_by(StrategyPerformanceRecord.created_at.desc())
        .all()
    )

    # Keep only the most recent backtest per strategy name.
    latest_by_strategy: dict[str, StrategyPerformanceRecord] = {}
    for record in records:
        latest_by_strategy.setdefault(record.strategy_name, record)

    candidates = []
    for name, record in latest_by_strategy.items():
        candidates.append(
            {
                "strategy_name": name,
                "total_return_pct": record.total_return_pct,
                "max_drawdown_pct": record.max_drawdown_pct,
                "sharpe_like_ratio": record.sharpe_like_ratio,
                "win_rate_pct": record.win_rate_pct,
                "within_risk_band": record.max_drawdown_pct <= band["max_drawdown_pct"],
            }
        )
    candidates.sort(key=lambda c: c["total_return_pct"], reverse=True)

    eligible = [c for c in candidates if c["within_risk_band"]]
    pool = eligible if eligible else candidates
    best = pool[0] if pool else None

    rationale = []
    if best is None:
        rationale.append("Nincs még elég backtest adat egyik stratégiához sem ehhez a szimbólumhoz.")
    else:
        rationale.append(
            f"{best['strategy_name']}: {best['total_return_pct']:.2f}% hozam, "
            f"{best['max_drawdown_pct']:.2f}% max visszaesés (sáv limit: {band['max_drawdown_pct']:.0f}%)"
        )
        if not eligible:
            rationale.append(
                f"Egyik stratégia sem fér bele a(z) \"{band['label']}\" kockázati sávba — "
                "ez a legjobb elérhető opció a jelenlegi adatok alapján."
            )

    return {
        "risk_level": risk_level,
        "recommended_strategy": best["strategy_name"] if best else None,
        "rationale": rationale,
        "candidates": candidates,
    }
