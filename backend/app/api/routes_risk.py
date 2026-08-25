from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from app.api.schemas import RecommendationOut
from app.db.database import SessionLocal
from app.risk.recommender import recommend_strategy

router = APIRouter(prefix="/recommendation", tags=["risk"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=RecommendationOut)
def get_recommendation(risk_level: str = "medium", symbol: str = "BTC/EUR", db: DbSession = Depends(get_db)):
    return recommend_strategy(db, risk_level, symbol)
