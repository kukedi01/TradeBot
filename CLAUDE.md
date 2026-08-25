# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A crypto paper-trading app: it connects to live Kraken market data and simulates trading strategies against it, so the user can measure whether active strategies actually beat simply holding (HODLing) before ever risking real money. **Phase 1 (current state) is paper-trading only** — no real orders are ever placed. Phase 2 (live trading via Kraken) is planned but not implemented.

Trading is in **EUR** (`BTC/EUR`, `ETH/EUR`, `SOL/EUR`, `XRP/EUR` — Kraken's native EUR pairs, no FX conversion needed). Internal field/column names still say `_usd` (e.g. `cash_usd`, `starting_balance_usd`) — that's a leftover from before the EUR pivot and was deliberately not renamed to avoid a bigger schema churn; treat those fields as EUR amounts.

The user is a beginner developer; work here proceeds in small, explained, verifiable steps rather than large unreviewed batches.

## Commands

Backend (from `backend/`, Windows/PowerShell):
```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload --reload-dir app
```
`--reload-dir app` matters: without it, uvicorn also watches `.venv/`, and any `pip install` inside it triggers a reload storm that can hang the reloader. No test suite exists yet. No linter/formatter is configured for the backend.

Frontend (from `frontend/`):
```
npm install
npm run dev       # Vite dev server on http://localhost:5173
npm run build      # tsc -b && vite build
npm run lint       # oxlint
```

Both dev servers must be running simultaneously for the app to work; the backend has no process manager or Docker setup — they're started as two separate local processes. The backend must run on port 8000 and the frontend on port 5173, since CORS in `backend/app/main.py` is hardcoded to allow only `http://localhost:5173`.

The SQLite database (`backend/cripto.db`) is created automatically via `Base.metadata.create_all()` on startup — there is **no migration system** (no Alembic). Adding/changing a column on an existing table requires deleting `cripto.db` and letting it recreate, since `create_all()` only creates missing tables, never alters existing ones. This has happened many times already; it's the normal workflow here, not a special event.

**Windows gotcha**: uvicorn's `--reload` can end up spawning its worker under the system Python instead of the venv Python if a stray process from an earlier run is still bound to port 8000. Before restarting the backend, check for and kill stray `python.exe` processes (`Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"`) rather than assuming the port is free.

## Architecture

### The execution engine seam (paper vs. future live trading)
`app/execution/base.py` defines an `ExecutionEngine` ABC (`place_order`, `get_balance`). `app/execution/paper_executor.py`'s `PaperExecutor` is the only implementation so far, and it deliberately only ever calls Kraken's **public/unauthenticated** ccxt endpoints (`get_ticker_price`) — this is a structural safety property, not just policy: Phase 1 code cannot place a real order even by mistake. A future `LiveKrakenExecutor` would implement the same interface with authenticated ccxt calls; strategies and the session loop only ever talk to the `ExecutionEngine` interface, never to ccxt directly, so swapping executors should not require touching strategy code. `place_order()` returns `Fill | None` — `None` means the order size rounded to zero quantity and was skipped rather than recorded as a no-op trade.

`app/execution/fill_simulator.py` holds the fee/slippage math (`simulate_fill`) as a pure function shared by both `PaperExecutor` (live paper trading) and the backtest engine — this keeps live and backtested fills numerically consistent (0.26% taker fee, 5bps slippage).

### Strategies
`app/strategies/base.py` defines the `Strategy` ABC: `on_tick(ctx: StrategyContext) -> list[TradeSignal]`. Three strategies implement it: `grid.py` (buy-the-dip/sell-the-rise across a fixed price band, with hysteresis via `min_move_pct` so tick-to-tick noise near a level boundary doesn't fire a trade, and band recentering if price wanders out of range for too long), `dca_rebalance.py` (scheduled buys + drift-triggered rebalance sells), `trend_momentum.py` (golden/death cross confirmed by a Bollinger middle-band check, not raw RSI-overbought). `app/strategies/registry.py`'s `STRATEGY_BUILDERS` dict maps a strategy name to a factory function `(symbol, current_price, size_fraction_override=None) -> Strategy` — the single place strategy defaults live; both live sessions and backtests build instances through it. `size_fraction_override` lets the live loop hand the strategy a Kelly-derived size instead of its hand-picked default.

`Strategy` also has generic `get_state()` / `load_state(state)` methods (in `base.py`) that snapshot/restore every instance attribute via `vars(self)` (with `set`/`deque` wrapped for JSON-safety) — this is how strategy memory survives a backend restart; see "Strategy state persistence" below. No subclass needs to implement its own serialization.

`StrategyContext` carries `symbol`, `price`, `cash_usd`, `holdings`, and two sentiment-derived fields, `pause_new_entries` and `size_multiplier` (see "News/sentiment module"). Strategies emit `TradeSignal(symbol, side, size_fraction, reason)`; `size_fraction` means "fraction of current cash" for a buy and "fraction of currently held qty" for a sell (see `fill_simulator.py`).

`"hold"` is a pseudo-strategy handled specially by name in `app/backtest/engine.py` (buy once, hold to the end) — it is **not** in `STRATEGY_BUILDERS` and cannot be selected as a live session strategy; it exists purely as the baseline that active strategies get compared against in backtests. (The live per-session HODL baseline is a different, newer mechanism — see "Portfolio snapshots / HODL baseline".)

### Regime detection and automatic strategy selection
`app/strategies/regime.py`'s `detect_regime(prices, previous_regime)` computes Kaufman's Efficiency Ratio (net price move ÷ total tick-to-tick distance travelled) to classify a coin's recent behavior as `"trending"` or `"ranging"`. It uses a **hysteresis band**, not one shared threshold: switching *into* trending needs the ratio ≥ 0.35 (`ENTER_TREND_THRESHOLD`), switching *out* only needs it to fall < 0.25 (`EXIT_TREND_THRESHOLD`) — this is the same fix pattern as the grid whipsaw bug, applied to prevent the regime (and thus the active strategy) from flapping back and forth on noise. `REGIME_STRATEGY` maps `"trending"` → `trend_momentum`, `"ranging"` → `grid`. `FALLBACK_STRATEGY = "grid"` is used until there are `MIN_HISTORY` (20) ticks of price history.

A session created with `strategy_name = "auto"` (the default — the frontend no longer offers manual strategy selection) uses this per-coin, per-tick: each of the 4 tradable coins can be run by a different strategy depending on its own recent behavior. All three strategies are kept ticking every cycle for every coin (so their internal state — grid levels, moving averages — stays warm even while inactive), but only the regime-selected strategy's **buy** signals get executed. A **sell** signal from *any* strategy always goes through regardless of which one is currently "active" — otherwise a coin bought while one strategy was active could get stranded with no strategy left willing to close it once the regime moves on. A session can still be created with a specific fixed strategy name (`"grid"`, `"dca_rebalance"`, `"trend_momentum"`) for that single-strategy behavior across all coins, though the frontend doesn't expose this anymore.

### Multi-coin trading
`app/session/loop.py`'s `TRADABLE_SYMBOLS = ["BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR"]` — a session doesn't trade one coin, it spreads its shared cash pool across all four; which coin actually reaches the goal doesn't matter. Every tick, `run_tick()` loops over all four symbols, running each coin's strategy/strategies against the *same* `Portfolio.cash_usd` and `Portfolio.holdings` (already a `{asset: qty}` dict, so this needed no schema change). Sizing is self-limiting: `size_fraction` on a buy means "fraction of *current* shared cash," so processing coins sequentially within one tick naturally prevents over-spending even though every coin's strategy independently thinks it can act on the full pool.

### News/sentiment module
`app/news/fetcher.py` pulls recent headlines from CoinDesk and Cointelegraph RSS feeds (no API key needed). `app/news/sentiment.py` scores each headline -1..1 with a small, readable keyword lexicon (`hack`, `ban`, `crash`, ... negative; `rally`, `etf approval`, `adoption`, ... positive). `app/news/reactor.py`'s `get_sentiment_state()` averages the scores across all fetched headlines and derives a `SentimentState` (`avg_sentiment`, `pause_new_entries`, `size_multiplier`) using its own thresholds (`PAUSE_THRESHOLD = -0.3`, `SEVERE_THRESHOLD = -0.6`); it's cached for 5 minutes (`CACHE_TTL`) so a 30s trading tick doesn't hit the RSS feeds every cycle. `session/loop.py` applies this centrally, not inside each strategy: a **buy** signal is dropped entirely if `pause_new_entries`, or shrunk by `size_multiplier` otherwise; a **sell** signal is never blocked by sentiment — bad news should never prevent getting out of a position.

### Risk guardrails (independent of any strategy)
`app/risk/guardrails.py`'s `check_drawdown_limit(current_value, past_values, max_drawdown_pct)` is a small, strategy-agnostic gatekeeper: every tick, `run_tick()` computes the session's total portfolio value (cash + all coin holdings at current prices), compares it to the highest value the session has ever reached (from its own `PortfolioSnapshot` history), and if the drawdown from that peak exceeds `TradingSession.max_drawdown_pct` (default 20%, set at session creation), the session's status flips to `"risk_stopped"` — regardless of what the active strategy thinks it's doing. This is deliberately separate from strategy logic (a "dumb," strict layer, not a smart one) and separate from the upside `target_balance` check. `POST /session/stop-all` is a kill switch that immediately stops every session in play (`"running"` or `"target_reached"`), independent of any one session's own logic.

### Strategy state persistence
`app/session/state_store.py`'s `save_state()` / `load_state()` read/write the `StrategyState` table, keyed by `(session_id, symbol, strategy_name)`. `session/loop.py` calls `strategy.get_state()` and persists it after every tick for every strategy touched (not just the active one), and on a cache-miss (first access after a process restart) calls `strategy.load_state()` to restore it before the strategy does anything — this is what lets a grid's exact band boundaries, owned levels, and hysteresis memory (and a DCA strategy's tick counter, and trend/momentum's moving-average history) survive a backend restart instead of resetting. The special `strategy_name` value `state_store.REGIME_HISTORY_KEY` (`"_regime_history"`) is reused for the same purpose to persist each coin's recent price history and last-known regime (used to seed the hysteresis check after a restart), even though it isn't a real strategy.

Note this doesn't make strategy state durable against *anything* — restarting mid-tick, concurrent writers, etc. aren't guarded against. It solves the specific, repeatedly-hit problem of "the dev server reloaded and the bot forgot everything."

### Live paper-trading loop
`app/session/loop.py`'s `run_tick(db, session_id)` is the per-session tick: for each of the 4 tradable symbols, fetch price → (in auto mode) update regime history and pick the active strategy → build `StrategyContext` (including the current sentiment state) → tick every candidate strategy for that coin → route buy signals from the active strategy (and sell signals from any strategy) through `PaperExecutor` → after all coins, record a `PortfolioSnapshot` and run the target/drawdown checks. Strategy instances are kept in an in-memory dict (`_strategy_instances`, keyed by `(session_id, symbol, strategy_name)`) for fast access within one process's lifetime; see "Strategy state persistence" for how this survives a restart.

`app/scheduler.py` runs an APScheduler job every 30s that calls `run_tick()` for every `TradingSession` with `status == "running"` — this is what makes paper trading happen automatically without the frontend polling triggering it. There's also a manual `POST /session/{id}/tick` endpoint for on-demand testing without waiting for the scheduler. If a tick takes longer than 30s (e.g. many running sessions × 4 coins × Kraken API latency), APScheduler logs a "maximum number of running instances reached" warning and skips that cycle rather than overlapping — not an error.

### Goal-based sessions
`TradingSession.target_balance` (optional) and `.max_drawdown_pct` (optional, default 20%) drive two independent auto-stop checks each tick. `status` is one of `"running"`, `"stopped"` (user-initiated, via `/stop` or `/stop-all`), `"target_reached"` (upside goal hit — the scheduler excludes non-`"running"` sessions, so it naturally pauses here), or `"risk_stopped"` (downside guardrail tripped). From `"target_reached"`, `POST /session/{id}/target` sets a new target and resumes the session to `"running"`; `"risk_stopped"` currently has no auto-resume path (closing it is the only action) — restarting after a risk-driven stop is meant to require a conscious decision, not a quick undo.

### Portfolio snapshots / HODL baseline
`TradingSession.starting_prices` (a `{symbol: price}` JSON dict, captured once at session creation) lets the app compute, at any later point, what an even split of the starting balance would be worth today if it had been bought once across all 4 coins and never touched again — the "HODL" comparison baseline, without needing to fetch historical OHLCV. Every tick, `run_tick()` inserts a `PortfolioSnapshot` row with both the session's actual `total_value_eur` and this `hodl_value_eur`. `GET /session/{id}/snapshots` returns the full time series; the frontend's `EquityChart.tsx` renders it as a hand-rolled inline-SVG line chart (bot vs. HODL, no charting library dependency).

### Backtesting
`app/backtest/engine.py`'s `run_backtest()` replays a strategy candle-by-candle over historical OHLCV using the same `simulate_fill()` as live trading, tracking an average cost basis to classify each closing trade as a win or loss. `app/backtest/data_loader.py` fetches historical OHLCV from Kraken via ccxt — **important gotcha**: Kraken's public OHLC endpoint only ever returns the most recent ~700 candles for a given timeframe, regardless of how far back `since` points, so requesting more history than that at a fine timeframe silently truncates to a recent window instead of erroring. `pick_timeframe()` picks a coarser timeframe (1h → 4h → 1d → 1w) as the requested day range grows, to stay under that cap; for an explicit date-range backtest (`fetch_ohlcv_between`), the timeframe choice is based on how far the *start* date is from *now*, not the window length, since Kraken's cap counts back from the present.

`app/backtest/validation.py` does a simple train/test split (not full walk-forward optimization) to check whether a strategy's behavior is consistent across different sub-periods, since strategies use fixed hand-picked parameters rather than parameters fit to the data. **Not yet covered**: the `"auto"` regime-switching mode has no backtest of its own — backtests still run one fixed strategy at a time.

### Risk/analysis module
`app/risk/profiles.py` defines risk bands (low/medium/high → max drawdown % caps) used for *backtest-based recommendation*, separate from the live per-session `max_drawdown_pct` guardrail described above. `app/risk/recommender.py` pulls each strategy's latest `StrategyPerformanceRecord` (including `"hold"`) for a symbol, filters to those within the chosen risk band's drawdown cap, and recommends the top return among eligible candidates — with a rationale and the full candidate list so the UI can show why. `app/risk/position_sizing.py`'s `kelly_fraction()` computes a half-Kelly, capped position size from a backtest's win/loss trade P&Ls (returns `max_fraction` rather than 0 when there are wins but no losses yet). `compute_kelly_size_for_strategy()` is wired into live sizing: `session/loop.py` calls it when first building a strategy instance and passes the result as `size_fraction_override`, falling back to the strategy's own default if the Kraken data call fails (e.g. rate limited) rather than failing the tick. `app/risk/monte_carlo.py`'s `run_monte_carlo()` bootstrap-resamples a backtest's daily returns to estimate VaR/CVaR and loss probabilities.

### API surface (all routers mounted in `app/main.py`)
- `GET /market/ticker/{symbol:path}` — live price (note the `:path` converter, needed because symbols like `BTC/EUR` contain a `/`)
- `/session` (`routes_session.py`) — create/stop/get a session, `GET /active` (most recent running/target-reached session, for the frontend to reconnect to on page load — see below), `POST /stop-all` (kill switch), `POST /{id}/target` (set new target, resume), place a manual order, list trades, list snapshots, get per-coin regime state, manual tick
- `/strategies` (`routes_strategies.py`) — lists `STRATEGY_BUILDERS` keys (does not include `"hold"` or `"auto"`)
- `/backtest` (`routes_backtest.py`) — run a backtest, train/test validate, Kelly position-size, Monte Carlo, list stored performance records
- `/recommendation` (`routes_risk.py`) — backtest-based strategy recommendation for a risk band
- `/news` (`routes_news.py`) — recent scored headlines + average sentiment; `/news/sentiment` — just the current `SentimentState`

### Frontend
Single-page app (`frontend/src/App.tsx`, no router/multiple pages yet). On mount, it calls `GET /session/active` to reconnect to whatever session is still running on the backend — the frontend holds no session id in storage, so without this, refreshing the page during a running session would silently lose track of it (the backend keeps running regardless; only the UI's view of it was lost). No manual strategy picker anymore — starting a session always uses `"auto"` mode; the pre-session panel still shows the risk-band recommendation panel (informational) plus starting balance, optional target, and the drawdown limit. A running session's panel shows: cash/holdings, a per-coin table of detected regime + active strategy (only when `strategy_name === "auto"`), the target-reached and risk-stopped banners (each with their own resolution actions), the `EquityChart` (bot vs. HODL), and the trade table. A global "🛑 Vészleállítás" button (kill switch, calls `stop-all`) sits in the header regardless of whether a session is loaded. A separate always-visible panel shows the live news feed and sentiment dot (red/yellow/green, same -0.3/+0.3 thresholds the bot itself reacts to), polled every 60s. The session panel polls every 5s while `status === "running"`. `frontend/src/api.ts` is a thin typed fetch wrapper around the backend — no other HTTP client library is used. `frontend/src/EquityChart.tsx` is a small hand-rolled inline-SVG chart component (no charting library).
