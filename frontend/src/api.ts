const API_BASE = "http://127.0.0.1:8000";

// Backend timestamps are UTC (Python's datetime.utcnow().isoformat() / naive
// DateTime columns) but serialized without a timezone suffix. Without "Z",
// the browser's Date parser treats the string as local time, shifting every
// displayed time by the viewer's own UTC offset (2h early/late in CET/CEST).
export function parseTimestamp(ts: string): Date {
  return new Date(ts.endsWith("Z") || ts.includes("+") ? ts : `${ts}Z`);
}

export interface Portfolio {
  cash_usd: number;
  holdings: Record<string, number>;
  // Weighted-average entry price per held asset -- what a position actually
  // cost, so the dashboard can show unrealized profit/loss next to its
  // current value.
  cost_basis: Record<string, number>;
}

export interface TradingSession {
  id: number;
  created_at: string;
  ended_at: string | null;
  status: string;
  starting_balance_usd: number;
  target_balance: number | null;
  max_drawdown_pct: number | null;
  strategy_name: string;
  portfolio: Portfolio;
}

export interface Trade {
  id: number;
  timestamp: string;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  fee: number;
  reason: string | null;
  realized_pnl: number | null;
  realized_pnl_pct: number | null;
}

export async function startSession(
  startingBalanceUsd: number,
  strategyName: string,
  targetBalance: number | null,
  maxDrawdownPct: number | null,
): Promise<TradingSession> {
  const res = await fetch(`${API_BASE}/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      starting_balance_usd: startingBalanceUsd,
      strategy_name: strategyName,
      target_balance: targetBalance,
      max_drawdown_pct: maxDrawdownPct,
    }),
  });
  return res.json();
}

export async function stopAllSessions(): Promise<TradingSession[]> {
  const res = await fetch(`${API_BASE}/session/stop-all`, { method: "POST" });
  return res.json();
}

export async function setTarget(sessionId: number, targetBalance: number | null): Promise<TradingSession> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/target`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_balance: targetBalance }),
  });
  return res.json();
}

export async function getStrategies(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/strategies`);
  const data = await res.json();
  return data.strategies;
}

export interface RecommendationCandidate {
  strategy_name: string;
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe_like_ratio: number;
  win_rate_pct: number;
  within_risk_band: boolean;
}

export interface Recommendation {
  risk_level: string;
  recommended_strategy: string | null;
  rationale: string[];
  candidates: RecommendationCandidate[];
}

export async function getRecommendation(riskLevel: string): Promise<Recommendation> {
  const res = await fetch(`${API_BASE}/recommendation?risk_level=${riskLevel}`);
  return res.json();
}

export async function getSession(sessionId: number): Promise<TradingSession> {
  const res = await fetch(`${API_BASE}/session/${sessionId}`);
  return res.json();
}

export async function getActiveSession(): Promise<TradingSession | null> {
  const res = await fetch(`${API_BASE}/session/active`);
  return res.json();
}

export async function stopSession(sessionId: number): Promise<TradingSession> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/stop`, { method: "POST" });
  return res.json();
}

export async function getTrades(sessionId: number): Promise<Trade[]> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/trades`);
  return res.json();
}

export async function tickNow(sessionId: number): Promise<{ executed: string[] }> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/tick`, { method: "POST" });
  return res.json();
}

export interface NewsItem {
  title: string;
  link: string;
  published: string | null;
  source: string;
  sentiment: number;
}

export interface NewsResponse {
  items: NewsItem[];
  avg_sentiment: number;
}

export async function getNews(): Promise<NewsResponse> {
  const res = await fetch(`${API_BASE}/news`);
  return res.json();
}

export interface SentimentState {
  avg_sentiment: number;
  headline_count: number;
  pause_new_entries: boolean;
  size_multiplier: number;
}

export async function getSentiment(): Promise<SentimentState> {
  const res = await fetch(`${API_BASE}/news/sentiment`);
  return res.json();
}

export interface RegimeEntry {
  symbol: string;
  regime: "trending" | "ranging" | null;
  active_strategy: string | null;
}

export async function getRegimeState(sessionId: number): Promise<RegimeEntry[]> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/regime`);
  const data = await res.json();
  return data.per_symbol;
}

export interface Snapshot {
  timestamp: string;
  total_value_eur: number;
  hodl_value_eur: number;
}

export type SnapshotPeriod = "1h" | "1d" | "1w" | "1m" | "6m" | "1y";

export async function getSnapshots(sessionId: number, period: SnapshotPeriod = "1d"): Promise<Snapshot[]> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/snapshots?period=${period}`);
  return res.json();
}

export interface Decision {
  timestamp: string;
  symbol: string;
  strategy: string;
  side: "buy" | "sell";
  reason?: string;
  detail?: string;
  outcome:
    | "executed"
    | "blocked_inactive_strategy"
    | "blocked_4h_downtrend"
    | "blocked_not_position_owner"
    | "blocked_handoff_below_cost_basis"
    | "blocked_sentiment_pause"
    | "zero_after_sizing"
    | "stop_loss_triggered";
  qty?: number;
  price?: number;
  shrunk_pct?: number;
}

export async function getDecisions(sessionId: number): Promise<Decision[]> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/decisions`);
  const data = await res.json();
  return data.decisions;
}

export interface CoinChartData {
  timestamps: string[];
  prices: number[];
  volumes: number[];
  rsi: (number | null)[];
  macd: (number | null)[];
  macd_signal: (number | null)[];
  macd_histogram: (number | null)[];
}

export async function getChartData(sessionId: number): Promise<Record<string, CoinChartData>> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/chart-data`);
  return res.json();
}

export interface DailyRange {
  symbol: string;
  high: number;
  low: number;
}

export async function getDailyRange(symbol: string): Promise<DailyRange> {
  const res = await fetch(`${API_BASE}/market/daily-range/${symbol}`);
  return res.json();
}

export interface MarketOverview {
  symbol: string;
  price: number | null;
  change_pct_24h: number | null;
  daily_high: number | null;
  daily_low: number | null;
}

export async function getMarketOverview(): Promise<MarketOverview[]> {
  const res = await fetch(`${API_BASE}/market/overview`);
  return res.json();
}

// The two prices a coin's grid is waiting for. Null thresholds mean there
// isn't one to name: trend_momentum enters on a moving-average cross rather
// than at a fixed price, and a freshly recentered grid has no "next step
// down" yet. See backend loop.get_strategy_plan.
export interface StrategyPlan {
  symbol: string;
  active_strategy: string | null;
  rule: string | null;
  next_buy_below: number | null;
  next_sell_above: number | null;
  band_low?: number;
  band_high?: number;
  level_count?: number;
  owned_levels?: number;
  current_level?: number | null;
}

export async function getPlan(sessionId: number): Promise<StrategyPlan[]> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/plan`);
  const data = await res.json();
  return data.per_symbol;
}

export interface StrategyPerformance {
  strategy: string;
  buys: number;
  sells: number;
  realized_pnl: number;
  fees: number;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
}

// Which strategy actually made or lost money -- attributed to whichever one
// *closed* each position, which is what makes a regime handoff visible.
export async function getStrategyPerformance(sessionId: number): Promise<StrategyPerformance[]> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/strategy-performance`);
  return res.json();
}

export interface MarketFlowSnapshot {
  timestamp: string;
  symbol: string;
  price: number;
  volume_delta: number;
  cumulative_volume_delta: number;
  trade_count: number;
  open_interest: number | null;
}

// Order-flow history. Nothing in the trading path reads this yet -- it's
// being accumulated so the signals can eventually be tested against real
// history (see backend market_data/flow.py).
export async function getMarketFlow(limit = 400): Promise<MarketFlowSnapshot[]> {
  const res = await fetch(`${API_BASE}/market/flow?limit=${limit}`);
  return res.json();
}
