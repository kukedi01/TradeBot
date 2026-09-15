"""Tests for run_tick's orchestration: which signals are allowed through,
which are blocked and why, and what gets recorded.

These cover the wiring *between* components, which is where this project's
two most expensive bugs actually lived -- neither was a fault in any single
strategy, and neither was reachable from the strategy-level tests.
"""
from app.db.models import DecisionLogEntry, Portfolio, PortfolioSnapshot, Trade, TradingSession
from app.session.loop import run_tick
from app.strategies.base import TradeSignal

from tests.conftest import ScriptedStrategy

SYMBOL = "BTC/EUR"


def buy(size=0.5, reason="test buy"):
    return TradeSignal(symbol=SYMBOL, side="buy", size_fraction=size, reason=reason)


def sell(size=1.0, reason="test sell"):
    return TradeSignal(symbol=SYMBOL, side="sell", size_fraction=size, reason=reason)


def trades_for(db, session_id, symbol=SYMBOL):
    return db.query(Trade).filter(Trade.session_id == session_id, Trade.symbol == symbol).all()


class TestRegimeGate:
    def test_grid_buy_executes_even_when_the_regime_favours_trend_momentum(self, db, make_session, loop_env):
        """The regression test for the gate that used to lock grid out.

        The label read "trending" 27-38% of the time, and through those
        stretches grid's buys were dropped while trend_momentum -- sized at
        0.08-0.24 by Kelly on most coins -- executed almost nothing. The bot
        sat idle for roughly a third of every session.
        """
        session_id = make_session()
        loop_env.set_regime("trend_momentum", "trending")
        loop_env.install(session_id, SYMBOL, {"grid": ScriptedStrategy("grid", [buy()])})

        run_tick(db, session_id)

        assert len(trades_for(db, session_id)) == 1
        assert "executed" in loop_env.outcomes(db, session_id, SYMBOL)

    def test_dca_rebalance_buy_is_blocked_when_it_is_not_the_active_strategy(self, db, make_session, loop_env):
        """dca_rebalance stays gated: it buys on a schedule rather than on a
        market condition, so ungated it would simply spend the pool."""
        session_id = make_session()
        loop_env.set_regime("grid", "ranging")
        loop_env.install(session_id, SYMBOL, {"dca_rebalance": ScriptedStrategy("dca_rebalance", [buy()])})

        run_tick(db, session_id)

        assert trades_for(db, session_id) == []
        assert "blocked_inactive_strategy" in loop_env.outcomes(db, session_id, SYMBOL)

    def test_a_blocked_signal_tells_the_strategy_it_was_not_filled(self, db, make_session, loop_env):
        """Without this, a strategy that marks itself "in position" at signal
        time stays permanently out of sync with what it actually holds."""
        session_id = make_session()
        loop_env.set_regime("grid", "ranging")
        strategy = ScriptedStrategy("dca_rebalance", [buy()])
        loop_env.install(session_id, SYMBOL, {"dca_rebalance": strategy})

        run_tick(db, session_id)

        assert strategy.not_filled_count == 1


class TestFourHourTrendFilter:
    def test_trend_momentum_buy_is_blocked_while_the_4h_trend_disagrees(self, db, make_session, loop_env):
        session_id = make_session()
        loop_env.set_regime("trend_momentum", "trending")
        loop_env.arm_hourly_candle_close(session_id, SYMBOL)
        loop_env.set_4h_uptrend(session_id, SYMBOL, False)
        loop_env.install(session_id, SYMBOL, {"trend_momentum": ScriptedStrategy("trend_momentum", [buy()])})

        run_tick(db, session_id)

        assert trades_for(db, session_id) == []
        assert "blocked_4h_downtrend" in loop_env.outcomes(db, session_id, SYMBOL)

    def test_unknown_4h_trend_blocks_rather_than_defaulting_open(self, db, make_session, loop_env):
        """Right after a session starts there isn't enough 4h history yet.
        That must read as "not confirmed", not as "no objection"."""
        session_id = make_session()
        loop_env.set_regime("trend_momentum", "trending")
        loop_env.arm_hourly_candle_close(session_id, SYMBOL)
        loop_env.install(session_id, SYMBOL, {"trend_momentum": ScriptedStrategy("trend_momentum", [buy()])})

        run_tick(db, session_id)

        assert trades_for(db, session_id) == []
        assert "blocked_4h_downtrend" in loop_env.outcomes(db, session_id, SYMBOL)

    def test_trend_momentum_buy_executes_once_the_4h_trend_agrees(self, db, make_session, loop_env):
        session_id = make_session()
        loop_env.set_regime("trend_momentum", "trending")
        loop_env.arm_hourly_candle_close(session_id, SYMBOL)
        loop_env.set_4h_uptrend(session_id, SYMBOL, True)
        loop_env.install(session_id, SYMBOL, {"trend_momentum": ScriptedStrategy("trend_momentum", [buy()])})

        run_tick(db, session_id)

        assert len(trades_for(db, session_id)) == 1


class TestSellOwnership:
    def test_sell_from_a_strategy_that_neither_owns_nor_is_active_is_blocked(self, db, make_session, loop_env):
        """Stops a background strategy from closing a position it had no
        thesis for, just because it can see nonzero holdings."""
        session_id = make_session(holdings={"BTC": 0.01}, cost_basis={"BTC": 50000.0}, cash=100.0)
        loop_env.set_regime("grid", "ranging")
        loop_env.set_owner(session_id, SYMBOL, "grid")
        loop_env.install(session_id, SYMBOL, {"dca_rebalance": ScriptedStrategy("dca_rebalance", [sell()])})

        run_tick(db, session_id)

        assert trades_for(db, session_id) == []
        assert "blocked_not_position_owner" in loop_env.outcomes(db, session_id, SYMBOL)

    def test_the_owner_can_always_sell_its_own_position(self, db, make_session, loop_env):
        """Cutting a losing position fast is the whole point of a
        trend-following exit, so the owner's own sell is never margin-gated."""
        session_id = make_session(holdings={"BTC": 0.01}, cost_basis={"BTC": 70000.0}, cash=100.0)
        loop_env.set_regime("grid", "ranging")
        loop_env.set_owner(session_id, SYMBOL, "trend_momentum")
        loop_env.install(session_id, SYMBOL, {"trend_momentum": ScriptedStrategy("trend_momentum", [sell()])})

        run_tick(db, session_id)

        assert len(trades_for(db, session_id)) == 1

    def test_handoff_sell_below_the_margin_is_blocked(self, db, make_session, loop_env):
        """A price a hair above cost basis still nets a loss once the sell
        fee lands, which is exactly how a handoff once realized a loss on XRP
        while "clearing" a zero-margin check."""
        session_id = make_session(holdings={"BTC": 0.01}, cost_basis={"BTC": 59990.0}, cash=100.0)
        loop_env.set_regime("grid", "ranging")
        loop_env.set_owner(session_id, SYMBOL, "trend_momentum")
        loop_env.install(session_id, SYMBOL, {"grid": ScriptedStrategy("grid", [sell()])})

        run_tick(db, session_id)

        assert trades_for(db, session_id) == []
        assert "blocked_handoff_below_cost_basis" in loop_env.outcomes(db, session_id, SYMBOL)

    def test_handoff_sell_clearing_the_margin_executes(self, db, make_session, loop_env):
        session_id = make_session(holdings={"BTC": 0.01}, cost_basis={"BTC": 50000.0}, cash=100.0)
        loop_env.set_regime("grid", "ranging")
        loop_env.set_owner(session_id, SYMBOL, "trend_momentum")
        loop_env.install(session_id, SYMBOL, {"grid": ScriptedStrategy("grid", [sell()])})

        run_tick(db, session_id)

        assert len(trades_for(db, session_id)) == 1

    def test_a_buy_records_its_strategy_as_the_position_owner(self, db, make_session, loop_env):
        session_id = make_session()
        loop_env.set_regime("grid", "ranging")
        loop_env.install(session_id, SYMBOL, {"grid": ScriptedStrategy("grid", [buy()])})

        run_tick(db, session_id)

        from app.session.loop import _position_owners

        assert _position_owners[(session_id, SYMBOL)] == "grid"

    def test_a_handoff_sell_tells_the_owner_its_position_is_gone(self, db, make_session, loop_env):
        """The bug this covers ran live on XRP: a handoff sell closed grid's
        whole position on a regime flip, nothing told grid, and grid went on
        listing levels 2/3/4 as owned -- so its next buy threshold skipped a
        1.19-1.23 EUR range it was actually flat in, silently refusing dips it
        should have bought. Only the stop-loss path sent this notification;
        the ordinary sell path never did.
        """
        session_id = make_session(holdings={"BTC": 0.01}, cost_basis={"BTC": 50000.0}, cash=100.0)
        loop_env.set_regime("grid", "ranging")
        loop_env.set_owner(session_id, SYMBOL, "trend_momentum")
        owner = ScriptedStrategy("trend_momentum")
        loop_env.install(
            session_id,
            SYMBOL,
            {"grid": ScriptedStrategy("grid", [sell()]), "trend_momentum": owner},
        )

        run_tick(db, session_id)

        assert len(trades_for(db, session_id)) == 1
        assert owner.external_sell_count == 1

    def test_a_partial_handoff_notifies_the_owner_but_not_the_seller(self, db, make_session, loop_env):
        """Clearing the seller's own position tracking would make it forget a
        position it still legitimately holds part of -- the notification is
        for the strategy the sell happened *to*, not the one making it."""
        session_id = make_session(holdings={"BTC": 0.01}, cost_basis={"BTC": 50000.0}, cash=100.0)
        loop_env.set_regime("grid", "ranging")
        loop_env.set_owner(session_id, SYMBOL, "trend_momentum")
        seller = ScriptedStrategy("grid", [sell(size=0.5)])
        owner = ScriptedStrategy("trend_momentum")
        loop_env.install(session_id, SYMBOL, {"grid": seller, "trend_momentum": owner})

        run_tick(db, session_id)

        assert owner.external_sell_count == 1
        assert seller.external_sell_count == 0

    def test_closing_the_position_out_notifies_every_strategy_including_the_seller(
        self, db, make_session, loop_env
    ):
        """Once holdings hit zero no strategy can still be holding a level,
        so the one that made the sell is told too -- grid's own sell frees a
        fraction of the holding rather than one specific level, so it can
        otherwise be left listing levels against an empty position."""
        session_id = make_session(holdings={"BTC": 0.01}, cost_basis={"BTC": 50000.0}, cash=100.0)
        loop_env.set_regime("grid", "ranging")
        loop_env.set_owner(session_id, SYMBOL, "grid")
        seller = ScriptedStrategy("grid", [sell(size=1.0)])
        other = ScriptedStrategy("dca_rebalance")
        loop_env.install(session_id, SYMBOL, {"grid": seller, "dca_rebalance": other})

        run_tick(db, session_id)

        assert len(trades_for(db, session_id)) == 1
        assert seller.external_sell_count == 1
        assert other.external_sell_count == 1


class TestSentiment:
    def test_a_sentiment_pause_blocks_buys(self, db, make_session, loop_env):
        session_id = make_session()
        loop_env.set_regime("grid", "ranging")
        loop_env.set_sentiment(pause_new_entries=True, avg_sentiment=-0.5)
        loop_env.install(session_id, SYMBOL, {"grid": ScriptedStrategy("grid", [buy()])})

        run_tick(db, session_id)

        assert trades_for(db, session_id) == []
        assert "blocked_sentiment_pause" in loop_env.outcomes(db, session_id, SYMBOL)

    def test_a_sentiment_pause_never_blocks_a_sell(self, db, make_session, loop_env):
        """Bad news must not trap the bot in a position."""
        session_id = make_session(holdings={"BTC": 0.01}, cost_basis={"BTC": 50000.0}, cash=100.0)
        loop_env.set_regime("grid", "ranging")
        loop_env.set_sentiment(pause_new_entries=True, avg_sentiment=-0.7)
        loop_env.set_owner(session_id, SYMBOL, "grid")
        loop_env.install(session_id, SYMBOL, {"grid": ScriptedStrategy("grid", [sell()])})

        run_tick(db, session_id)

        assert len(trades_for(db, session_id)) == 1

    def test_a_shrinking_sentiment_multiplier_is_recorded_on_the_decision(self, db, make_session, loop_env):
        session_id = make_session()
        loop_env.set_regime("grid", "ranging")
        loop_env.set_sentiment(size_multiplier=0.5, avg_sentiment=-0.2)
        loop_env.install(session_id, SYMBOL, {"grid": ScriptedStrategy("grid", [buy()])})

        run_tick(db, session_id)

        executed = [d for d in loop_env.decisions(db, session_id) if d["outcome"] == "executed"]
        assert executed and executed[0]["shrunk_pct"] == 50.0


class TestStopLoss:
    def test_a_position_far_below_its_entry_is_force_sold(self, db, make_session, loop_env):
        """The guardrail runs before any strategy ticks, because a strategy's
        own exit condition can lag well behind a fast drop."""
        session_id = make_session(holdings={"BTC": 0.01}, cost_basis={"BTC": 100000.0}, cash=100.0)
        loop_env.set_regime("grid", "ranging")

        run_tick(db, session_id)

        sells = [t for t in trades_for(db, session_id) if t.side == "sell"]
        assert len(sells) == 1
        assert "stop-loss" in sells[0].reason
        assert "stop_loss_triggered" in loop_env.outcomes(db, session_id, SYMBOL)

    def test_a_forced_sale_tells_the_strategies_their_position_is_gone(self, db, make_session, loop_env):
        """Otherwise grid keeps believing it owns levels it no longer holds
        and refuses to re-buy them."""
        session_id = make_session(holdings={"BTC": 0.01}, cost_basis={"BTC": 100000.0}, cash=100.0)
        loop_env.set_regime("grid", "ranging")
        strategy = ScriptedStrategy("grid")
        loop_env.install(session_id, SYMBOL, {"grid": strategy})

        run_tick(db, session_id)

        assert strategy.external_sell_count == 1


class TestSessionLifecycle:
    def test_each_tick_records_a_snapshot_of_bot_and_hodl_value(self, db, make_session, loop_env):
        session_id = make_session()
        loop_env.set_regime("grid", "ranging")

        run_tick(db, session_id)

        snapshots = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.session_id == session_id).all()
        assert len(snapshots) == 1
        # No trades happened and prices match the session's starting prices,
        # so the bot and an untouched even split are worth the same.
        assert snapshots[0].total_value_eur == 1000.0
        assert abs(snapshots[0].hodl_value_eur - 1000.0) < 1e-6

    def test_reaching_the_target_stops_the_session(self, db, make_session, loop_env):
        session_id = make_session(target_balance=500.0)
        loop_env.set_regime("grid", "ranging")

        run_tick(db, session_id)

        assert db.get(TradingSession, session_id).status == "target_reached"

    def test_a_drawdown_breach_flips_the_session_to_risk_stopped(self, db, make_session, loop_env):
        """The guardrail compares against the session's own peak, so a prior
        snapshot has to exist for there to be a peak to fall from."""
        session_id = make_session(max_drawdown_pct=5.0)
        loop_env.set_regime("grid", "ranging")
        db.add(PortfolioSnapshot(session_id=session_id, total_value_eur=2000.0, hodl_value_eur=2000.0))
        db.commit()

        run_tick(db, session_id)

        assert db.get(TradingSession, session_id).status == "risk_stopped"

    def test_a_stopped_session_is_left_alone(self, db, make_session, loop_env):
        session_id = make_session()
        session = db.get(TradingSession, session_id)
        session.status = "stopped"
        db.commit()
        loop_env.set_regime("grid", "ranging")
        loop_env.install(session_id, SYMBOL, {"grid": ScriptedStrategy("grid", [buy()])})

        run_tick(db, session_id)

        assert db.get(TradingSession, session_id).status == "stopped"


class TestSizingAcrossTheSharedPool:
    def test_cash_spent_on_one_coin_is_not_available_to_the_next(self, db, make_session, loop_env):
        """All four coins draw on one pool, so a buy earlier in the tick has
        to shrink what a later one can spend -- otherwise each coin sizes
        itself as though it owned the whole balance."""
        session_id = make_session(starting_balance=1000.0)
        loop_env.set_regime("grid", "ranging")
        loop_env.install(session_id, "BTC/EUR", {"grid": ScriptedStrategy("grid", [buy(size=1.0)])})
        loop_env.install(
            session_id,
            "ETH/EUR",
            {"grid": ScriptedStrategy("grid", [TradeSignal("ETH/EUR", "buy", 1.0, "test buy")])},
        )

        run_tick(db, session_id)

        portfolio = db.get(Portfolio, session_id)
        assert portfolio.cash_usd >= 0
        btc_value = portfolio.holdings.get("BTC", 0) * 60000.0
        eth_value = portfolio.holdings.get("ETH", 0) * 2000.0
        assert btc_value + eth_value + portfolio.cash_usd <= 1000.0 + 1e-6


class TestDecisionLogPersistence:
    def test_decisions_are_written_to_the_database_not_just_memory(self, db, make_session, loop_env):
        """The whole point of moving this out of a deque: a restart used to
        erase the record of why the bot didn't trade, 8 times over one
        194-hour session."""
        session_id = make_session()
        loop_env.set_regime("grid", "ranging")
        loop_env.install(session_id, SYMBOL, {"dca_rebalance": ScriptedStrategy("dca_rebalance", [buy()])})

        run_tick(db, session_id)

        rows = db.query(DecisionLogEntry).filter(DecisionLogEntry.session_id == session_id).all()
        assert [r.outcome for r in rows] == ["blocked_inactive_strategy"]
        assert rows[0].strategy == "dca_rebalance"

    def test_an_executed_decision_records_the_quantity_and_price(self, db, make_session, loop_env):
        """Per-strategy attribution needs these; without them an executed row
        says a trade happened but not how large it was."""
        session_id = make_session()
        loop_env.set_regime("grid", "ranging")
        loop_env.install(session_id, SYMBOL, {"grid": ScriptedStrategy("grid", [buy()])})

        run_tick(db, session_id)

        executed = (
            db.query(DecisionLogEntry)
            .filter(DecisionLogEntry.session_id == session_id, DecisionLogEntry.outcome == "executed")
            .one()
        )
        assert executed.qty > 0
        # The fill price, not the raw market price -- it carries the slippage
        # the order actually paid (5bps above 60000 on a buy).
        assert executed.price == 60030.0
        assert executed.strategy == "grid"
