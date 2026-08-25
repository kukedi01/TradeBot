from fastapi import APIRouter

from app.strategies.registry import STRATEGY_BUILDERS

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("")
def list_strategies():
    return {"strategies": list(STRATEGY_BUILDERS.keys())}
