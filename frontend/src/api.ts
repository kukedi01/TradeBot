const API_BASE = "http://127.0.0.1:8000";

export interface Portfolio {
  cash_usd: number;
  holdings: Record<string, number>;
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

export async function getSnapshots(sessionId: number): Promise<Snapshot[]> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/snapshots`);
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
