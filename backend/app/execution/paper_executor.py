from datetime import datetime

from sqlalchemy.orm import Session as DbSession

from app.db.models import Portfolio, Trade
from app.execution.base import ExecutionEngine, Fill
from app.execution.fill_simulator import simulate_fill
from app.market_data.kraken_client import get_ticker_price


class PaperExecutor(ExecutionEngine):
    def __init__(self, db: DbSession, session_id: int):
        self.db = db
        self.session_id = session_id

    def _portfolio(self) -> Portfolio:
        return self.db.get(Portfolio, self.session_id)

    def get_balance(self) -> dict:
        portfolio = self._portfolio()
        return {"cash_usd": portfolio.cash_usd, "holdings": portfolio.holdings}

    def place_order(self, symbol: str, side: str, size_fraction: float, reason: str) -> Fill | None:
        base_asset = symbol.split("/")[0]
        market_price = get_ticker_price(symbol)

        portfolio = self._portfolio()
        holdings = dict(portfolio.holdings or {})
        held_qty = holdings.get(base_asset, 0)
        cost_basis = dict(portfolio.cost_basis or {})
        avg_cost = cost_basis.get(base_asset, 0.0)

        fill_price, qty, fee = simulate_fill(market_price, side, size_fraction, portfolio.cash_usd, held_qty)

        if qty <= 0:
            # Nothing meaningful to trade (e.g. cash or holdings too small
            # relative to the order size) -- skip instead of recording a
            # zero-quantity trade and still charging a fee's worth of noise.
            return None

        if side == "buy":
            portfolio.cash_usd -= fill_price * qty + fee
            # Weighted-average cost basis, same formula the backtest engine
            # uses -- naturally resets to fill_price when held_qty is 0, so
            # no separate reset is needed once a position is fully closed.
            cost_basis[base_asset] = (avg_cost * held_qty + fill_price * qty) / (held_qty + qty)
            holdings[base_asset] = held_qty + qty
        else:
            portfolio.cash_usd += fill_price * qty - fee
            holdings[base_asset] = held_qty - qty

        portfolio.holdings = holdings
        portfolio.cost_basis = cost_basis
        portfolio.updated_at = datetime.utcnow()

        trade = Trade(
            session_id=self.session_id,
            timestamp=datetime.utcnow(),
            symbol=symbol,
            side=side,
            qty=qty,
            price=fill_price,
            fee=fee,
            reason=reason,
        )
        self.db.add(trade)
        self.db.commit()
        self.db.refresh(portfolio)

        return Fill(symbol=symbol, side=side, qty=qty, price=fill_price, fee=fee)
