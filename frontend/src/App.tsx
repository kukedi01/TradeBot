import { useEffect, useState } from "react";
import {
  getActiveSession,
  getChartData,
  getDecisions,
  getMarketFlow,
  getMarketOverview,
  getNews,
  getPlan,
  getRecommendation,
  getRegimeState,
  getSentiment,
  getSession,
  getSnapshots,
  getStrategyPerformance,
  getTrades,
  parseTimestamp,
  setTarget,
  startSession,
  stopAllSessions,
  stopSession,
  tickNow,
  type CoinChartData,
  type Decision,
  type MarketFlowSnapshot,
  type MarketOverview,
  type NewsItem,
  type Recommendation,
  type RegimeEntry,
  type SentimentState,
  type Snapshot,
  type SnapshotPeriod,
  type StrategyPerformance,
  type StrategyPlan,
  type Trade,
  type TradingSession,
} from "./api";
import { CoinCard } from "./CoinCard";
import { CoinChart } from "./CoinChart";
import { EquityChart } from "./EquityChart";
import { Sparkline } from "./Sparkline";
import { eur, fmt, priceDigits, signed, signedEur, signedPct, timeOfDay, timeWithSeconds } from "./format";
import {
  OUTCOME_CLASS,
  OUTCOME_LABELS,
  STRATEGY_DESCRIPTIONS,
  STRATEGY_LABELS,
  sentimentColor,
} from "./labels";
import "./App.css";

const TRADABLE_SYMBOLS = ["BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR"];

const RISK_LABELS: Record<string, string> = {
  low: "Alacsony",
  medium: "Közepes",
  high: "Magas",
};

const STATUS_LABELS: Record<string, string> = {
  running: "Fut",
  stopped: "Leállítva",
  target_reached: "Cél elérve",
  risk_stopped: "Kockázati stop",
};

const PERIOD_LABELS: Record<SnapshotPeriod, string> = {
  "1h": "Óra",
  "1d": "Nap",
  "1w": "Hét",
  "1m": "Hónap",
  "6m": "Fél év",
  "1y": "Év",
};
const PERIOD_OPTIONS: SnapshotPeriod[] = ["1h", "1d", "1w", "1m", "6m", "1y"];

// Cash first, then the coins in TRADABLE_SYMBOLS order.
const ALLOC_COLORS = ["var(--neutral-line)", "var(--sage)", "#6f8c78", "#9bb0a2", "var(--clay)"];

/* ------------------------------------------------------------------ icons */

function IconTrendUp() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#faf6ee" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 17l5-6 4 4 7-9" />
      <path d="M15 6h4v4" />
    </svg>
  );
}

function IconStop() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M8 8l8 8" />
    </svg>
  );
}

function IconBuy() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--up)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 19V5" />
      <path d="M5 12l7-7 7 7" />
    </svg>
  );
}

function IconSell() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--down)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 5v14" />
      <path d="M19 12l-7 7-7-7" />
    </svg>
  );
}

function IconRisk() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--clay)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 8v5" />
      <path d="M12 16.5v.5" />
      <path d="M10.3 3.9L2.5 18a1.7 1.7 0 001.5 2.6h16a1.7 1.7 0 001.5-2.6L13.7 3.9a1.7 1.7 0 00-3 0z" />
    </svg>
  );
}

/* ------------------------------------------------------------- helpers */

function formatRuntime(createdAt: string): string {
  const ms = Date.now() - parseTimestamp(createdAt).getTime();
  const hours = ms / 3_600_000;
  if (hours < 48) return `${Math.max(Math.round(hours), 0)} óra`;
  return `${Math.round(hours / 24)} nap`;
}

// A trade's `reason` is the strategy's own wording ("grid: dip to level 3").
// The sentence above it says what happened in plain Hungarian; the reason
// itself stays underneath rather than being rewritten, so nothing is lost.
function tradeSentence(trade: Trade): string {
  const base = trade.symbol.split("/")[0];
  const amount = eur(trade.qty * trade.price);
  if ((trade.reason ?? "").startsWith("risk")) {
    return `Kényszer-eladás ${base}-ből ${amount} értékben (stop-loss).`;
  }
  return trade.side === "buy" ? `Vett ${base}-t ${amount} értékben.` : `Eladott ${base}-t ${amount} értékben.`;
}

function App() {
  const [session, setSession] = useState<TradingSession | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);
  const [regimeState, setRegimeState] = useState<RegimeEntry[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [strategyPerf, setStrategyPerf] = useState<StrategyPerformance[]>([]);
  const [snapshotPeriod, setSnapshotPeriod] = useState<SnapshotPeriod>("1d");
  const [plans, setPlans] = useState<StrategyPlan[]>([]);
  const [onlyExecutedTrades, setOnlyExecutedTrades] = useState(false);
  const [chartData, setChartData] = useState<Record<string, CoinChartData>>({});
  const [overview, setOverview] = useState<MarketOverview[]>([]);
  const [flow, setFlow] = useState<MarketFlowSnapshot[]>([]);
  const [riskLevel, setRiskLevel] = useState("medium");
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [startingBalance, setStartingBalance] = useState(1000);
  const [targetInput, setTargetInput] = useState(2000);
  const [useTarget, setUseTarget] = useState(true);
  const [newTargetInput, setNewTargetInput] = useState(0);
  const [maxDrawdownInput, setMaxDrawdownInput] = useState(20);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [sentiment, setSentiment] = useState<SentimentState | null>(null);

  useEffect(() => {
    const refreshNews = () => {
      getNews().then((res) => setNews(res.items.slice(0, 8)));
      getSentiment().then(setSentiment);
    };
    refreshNews();
    const interval = setInterval(refreshNews, 60000);
    return () => clearInterval(interval);
  }, []);

  // Market data is not session-scoped: the ticker overview and the order-flow
  // history keep accumulating whether or not a session is running, so they
  // refresh on their own timer. The backend caches the overview for 30s, so
  // polling faster than that would only re-read the same cache.
  useEffect(() => {
    const refreshMarket = () => {
      getMarketOverview().then(setOverview).catch(() => undefined);
      getMarketFlow(400).then(setFlow).catch(() => undefined);
    };
    refreshMarket();
    const interval = setInterval(refreshMarket, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    getRecommendation(riskLevel).then(setRecommendation);
  }, [riskLevel]);

  const refresh = async (sessionId: number, period: SnapshotPeriod) => {
    const [
      updatedSession,
      updatedTrades,
      updatedRegime,
      updatedSnapshots,
      updatedDecisions,
      updatedChartData,
      updatedPerf,
      updatedPlans,
    ] = await Promise.all([
      getSession(sessionId),
      getTrades(sessionId),
      getRegimeState(sessionId),
      getSnapshots(sessionId, period),
      getDecisions(sessionId),
      getChartData(sessionId),
      getStrategyPerformance(sessionId),
      getPlan(sessionId),
    ]);
    setSession(updatedSession);
    setTrades(updatedTrades);
    setRegimeState(updatedRegime);
    setSnapshots(updatedSnapshots);
    setDecisions(updatedDecisions);
    setChartData(updatedChartData);
    setStrategyPerf(updatedPerf);
    setPlans(updatedPlans);
  };

  // Refetches immediately when the session or the chosen chart period
  // changes (so picking "Év" doesn't wait up to 5s to show up), then polls
  // on the usual cadence while the session is running.
  useEffect(() => {
    if (!session) return;
    refresh(session.id, snapshotPeriod);
    if (session.status !== "running") return;
    const interval = setInterval(() => refresh(session.id, snapshotPeriod), 5000);
    return () => clearInterval(interval);
  }, [session?.id, session?.status, snapshotPeriod]);

  // On page load, reconnect to whatever session is still running on the
  // backend instead of showing an empty "start a session" screen for it.
  useEffect(() => {
    getActiveSession().then((active) => {
      if (active) refresh(active.id, snapshotPeriod);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only ever meant to run once, on mount
  }, []);

  const handleStart = async () => {
    setLoading(true);
    const newSession = await startSession(startingBalance, "auto", useTarget ? targetInput : null, maxDrawdownInput);
    setSession(newSession);
    setTrades([]);
    setLoading(false);
  };

  const handleStopAll = async () => {
    setLoading(true);
    await stopAllSessions();
    setSession(null);
    setLoading(false);
  };

  const handleStop = async () => {
    if (!session) return;
    setLoading(true);
    await stopSession(session.id);
    await refresh(session.id, snapshotPeriod);
    setLoading(false);
  };

  const handleTick = async () => {
    if (!session) return;
    setLoading(true);
    await tickNow(session.id);
    await refresh(session.id, snapshotPeriod);
    setLoading(false);
  };

  const handleSetNewTarget = async () => {
    if (!session) return;
    setLoading(true);
    await setTarget(session.id, newTargetInput);
    await refresh(session.id, snapshotPeriod);
    setLoading(false);
  };

  /* ------------------------------------------------------- derived data */

  const overviewBySymbol: Record<string, MarketOverview> = {};
  overview.forEach((o) => {
    overviewBySymbol[o.symbol] = o;
  });

  const regimeBySymbol: Record<string, RegimeEntry> = {};
  regimeState.forEach((r) => {
    regimeBySymbol[r.symbol] = r;
  });

  const planBySymbol: Record<string, StrategyPlan> = {};
  plans.forEach((p) => {
    planBySymbol[p.symbol] = p;
  });

  const latestSnapshot = snapshots.length > 0 ? snapshots[snapshots.length - 1] : null;
  const peakValue = snapshots.reduce((peak, s) => Math.max(peak, s.total_value_eur), 0);
  const drawdownPct = latestSnapshot && peakValue > 0 ? ((peakValue - latestSnapshot.total_value_eur) / peakValue) * 100 : 0;
  const diffVsHodl = latestSnapshot ? latestSnapshot.total_value_eur - latestSnapshot.hodl_value_eur : 0;
  const diffPct = latestSnapshot && latestSnapshot.hodl_value_eur > 0 ? (diffVsHodl / latestSnapshot.hodl_value_eur) * 100 : 0;

  const buyCount = trades.filter((t) => t.side === "buy").length;
  const sellCount = trades.length - buyCount;
  const closedTrades = trades.filter((t) => t.realized_pnl != null);
  const winCount = closedTrades.filter((t) => (t.realized_pnl ?? 0) > 0).length;
  const totalFees = trades.reduce((sum, t) => sum + t.fee, 0);

  const recentTrades = [...trades].reverse().slice(0, 6);

  const blockedCounts: Record<string, number> = {};
  decisions
    .filter((d) => d.outcome !== "executed")
    .forEach((d) => {
      blockedCounts[d.outcome] = (blockedCounts[d.outcome] ?? 0) + 1;
    });
  const blockedRanked = Object.entries(blockedCounts).sort((a, b) => b[1] - a[1]);
  const blockedMax = blockedRanked.length > 0 ? blockedRanked[0][1] : 1;
  const blockedTotal = blockedRanked.reduce((sum, [, count]) => sum + count, 0);
  const recentBlocked = decisions.filter((d) => d.outcome !== "executed").slice(0, 4);

  const filteredDecisions = onlyExecutedTrades ? decisions.filter((d) => d.outcome === "executed") : decisions;

  const holdingRows = TRADABLE_SYMBOLS.map((symbol) => {
    const asset = symbol.split("/")[0];
    const qty = session?.portfolio.holdings[asset] ?? 0;
    const price = overviewBySymbol[symbol]?.price ?? null;
    return { symbol, asset, qty, price, value: price !== null ? qty * price : 0 };
  });
  const coinTotal = holdingRows.reduce((sum, row) => sum + row.value, 0);
  const cash = session?.portfolio.cash_usd ?? 0;
  const portfolioTotal = cash + coinTotal;

  const latestFlow: Record<string, MarketFlowSnapshot> = {};
  flow.forEach((row) => {
    latestFlow[row.symbol] = row;
  });
  const btcFlowSeries = flow.filter((r) => r.symbol === "BTC/EUR").map((r) => r.cumulative_volume_delta);

  /* ------------------------------------------------------------ render */

  const newsCard = (
    <section className="card">
      <div className="card-lead">Mit mondanak a hírek</div>
      <p className="card-note">
        {sentiment?.pause_new_entries
          ? `A hangulat elég rossz ahhoz, hogy a bot most ne nyisson új pozíciót (tétméret ×${sentiment.size_multiplier}).`
          : "Jó hangulatnál a bot normál mérettel vásárol, rosszra magától kisebbet lép, nagyon rosszra megáll."}
      </p>
      {sentiment && (
        <>
          <div className="sentiment-row">
            <span className="chip-dot" style={{ color: sentimentColor(sentiment.avg_sentiment) }} />
            <span className="sentiment-value">{signed(sentiment.avg_sentiment, 2)}</span>
            <span className="small muted">{sentiment.headline_count} hír alapján</span>
          </div>
          <div className="sentiment-scale">
            <div className="sentiment-mark" style={{ left: `calc(${((sentiment.avg_sentiment + 1) / 2) * 100}% - 1.5px)` }} />
          </div>
          <div className="sentiment-ends">
            <span>−1,00 rossz</span>
            <span>+1,00 jó</span>
          </div>
        </>
      )}
      {news.length === 0 ? (
        <p className="muted small">Hírek betöltése…</p>
      ) : (
        news.slice(0, 4).map((item) => (
          <div className="news-item" key={item.link}>
            <span className="news-dot" style={{ background: sentimentColor(item.sentiment) }} />
            <span>
              <a href={item.link} target="_blank" rel="noreferrer">
                {item.title}
              </a>
              <span className="news-meta">
                {item.source} · {signed(item.sentiment, 2)}
              </span>
            </span>
          </div>
        ))
      )}
    </section>
  );

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark">
            <IconTrendUp />
          </div>
          <div>
            <div className="brand-name">Kripto kísérlet</div>
            <div className="brand-meta">
              {session
                ? `${session.id}. session · ${formatRuntime(session.created_at)} · automatikus stratégia · szimulált pénz`
                : "Szimulált kereskedés élő Kraken adatokon — valódi megbízás soha nem megy ki."}
            </div>
          </div>
        </div>
        <div className="header-actions">
          {session && (
            <span className={`chip ${session.status === "running" ? "chip-live" : "chip-idle"}`}>
              <span className="chip-dot" />
              {STATUS_LABELS[session.status] ?? session.status}
            </span>
          )}
          {session && (
            <>
              <button onClick={handleTick} disabled={loading || session.status !== "running"}>
                Lépés most
              </button>
              <button onClick={handleStop} disabled={loading || session.status === "stopped"}>
                Szüneteltetés
              </button>
            </>
          )}
          <button className="btn-danger" onClick={handleStopAll} disabled={loading}>
            <IconStop />
            Mindent leállít
          </button>
        </div>
      </header>

      {/* ------------------------------------------------ session indítás */}
      {!session && (
        <div className="grid grid-3">
          <section className="card span-2">
            <div className="card-lead">Indítsunk egy kísérletet</div>
            <p className="card-note">
              A bot coinonként (BTC, ETH, SOL, XRP) folyamatosan figyeli, hogy trendelő vagy oldalazó piacon vagyunk, és
              ez alapján maga választ stratégiát — nincs kézi stratégiaválasztás.
            </p>

            <div className="setup-grid">
              <div className="field">
                <span className="field-label">Kezdő összeg (EUR)</span>
                <input type="number" value={startingBalance} onChange={(e) => setStartingBalance(Number(e.target.value))} />
              </div>
              <div className="field">
                <span className="field-label">Célösszeg (EUR)</span>
                <input
                  type="number"
                  value={targetInput}
                  disabled={!useTarget}
                  onChange={(e) => setTargetInput(Number(e.target.value))}
                />
                <label>
                  <input type="checkbox" checked={useTarget} onChange={(e) => setUseTarget(e.target.checked)} />
                  Célösszeg kitűzése
                </label>
              </div>
              <div className="field">
                <span className="field-label">Vesztés-limit (%)</span>
                <input type="number" value={maxDrawdownInput} onChange={(e) => setMaxDrawdownInput(Number(e.target.value))} />
                <span className="small faint">
                  Ha a portfólió ennyit esik a csúcsától, a bot magától leáll.
                </span>
              </div>
            </div>

            <div className="button-row">
              <span className="field-label">Kockázati szint:</span>
              {Object.entries(RISK_LABELS).map(([value, label]) => (
                <button
                  key={value}
                  className={riskLevel === value ? "btn-selected" : ""}
                  onClick={() => setRiskLevel(value)}
                >
                  {label}
                </button>
              ))}
            </div>

            {recommendation && (
              <div style={{ marginTop: 20 }}>
                <p className="small muted">
                  Ajánlott stratégia a backtestek alapján: <strong>{recommendation.recommended_strategy ?? "—"}</strong>
                </p>
                {recommendation.rationale.map((line, i) => (
                  <p key={i} className="small faint">
                    {line}
                  </p>
                ))}
                <div className="rec-row row-head" style={{ marginTop: 12 }}>
                  <div>STRATÉGIA</div>
                  <div className="right">HOZAM</div>
                  <div className="right">MAX VISSZAESÉS</div>
                  <div className="right">TALÁLAT</div>
                  <div className="right">BELEFÉR?</div>
                </div>
                {recommendation.candidates.map((c) => (
                  <div className="rec-row row" key={c.strategy_name}>
                    <div>{STRATEGY_LABELS[c.strategy_name] ?? c.strategy_name}</div>
                    <div className="right mono">{signedPct(c.total_return_pct)}</div>
                    <div className="right mono">{fmt(c.max_drawdown_pct)}%</div>
                    <div className="right mono">{fmt(c.win_rate_pct, 1)}%</div>
                    <div className="right">{c.within_risk_band ? "igen" : "nem"}</div>
                  </div>
                ))}
              </div>
            )}

            <div className="button-row">
              <button className="btn-primary" onClick={handleStart} disabled={loading}>
                Kísérlet indítása
              </button>
            </div>
          </section>

          {newsCard}
        </div>
      )}

      {/* ------------------------------------------------------- futó session */}
      {session && (
        <>
          <section className="card card-hero">
            <div className="verdict-body">
              <div className="verdict-claim">
                <div className="verdict-headline">
                  {latestSnapshot ? (
                    <>
                      A bot most{" "}
                      <span className={diffVsHodl >= 0 ? "pos" : "neg"}>{signedEur(diffVsHodl)}</span>
                      {diffVsHodl >= 0 ? "-val áll jobban" : "-val áll rosszabbul"}, mint ha csak megvetted volna és
                      tartanád.
                    </>
                  ) : (
                    <>Most indult — az első mérés néhány tick múlva lesz.</>
                  )}
                </div>
                <div className="verdict-figures">
                  <div>
                    <div className="figure-label">A bot portfóliója</div>
                    <div className="figure-value">{eur(latestSnapshot?.total_value_eur ?? portfolioTotal)}</div>
                    <div className="figure-sub">
                      {signedPct(
                        (((latestSnapshot?.total_value_eur ?? portfolioTotal) - session.starting_balance_usd) /
                          session.starting_balance_usd) *
                          100,
                      )}{" "}
                      a {eur(session.starting_balance_usd, 0)}-ról
                    </div>
                  </div>
                  <div>
                    <div className="figure-label">Ha csak tartanád</div>
                    <div className="figure-value figure-value-muted">{eur(latestSnapshot?.hodl_value_eur ?? session.starting_balance_usd)}</div>
                    <div className="figure-sub">
                      {signedPct(
                        (((latestSnapshot?.hodl_value_eur ?? session.starting_balance_usd) - session.starting_balance_usd) /
                          session.starting_balance_usd) *
                          100,
                      )}{" "}
                      a {eur(session.starting_balance_usd, 0)}-ról
                    </div>
                  </div>
                </div>
                <p className="verdict-aside">
                  Ez az a kérdés, amiért az egész program készült: megéri-e aktívan kereskedni a sima tartás helyett.
                  {latestSnapshot && (
                    <>
                      {" "}
                      Eddig <strong>{diffVsHodl >= 0 ? "igen" : "nem"}</strong> — {signedPct(diffPct)} eltérés.
                    </>
                  )}
                </p>
              </div>
              <div className="verdict-chart">
                <div className="period-picker">
                  {PERIOD_OPTIONS.map((p) => (
                    <button
                      key={p}
                      className={snapshotPeriod === p ? "btn-selected" : ""}
                      onClick={() => setSnapshotPeriod(p)}
                    >
                      {PERIOD_LABELS[p]}
                    </button>
                  ))}
                </div>
                <EquityChart snapshots={snapshots} />
              </div>
            </div>

            <div className="meters">
              <div>
                <div className="meter-label">Futásidő</div>
                <div className="meter-value">{formatRuntime(session.created_at)}</div>
              </div>
              <div>
                <div className="meter-label">Kötések</div>
                <div className="meter-value">{trades.length}</div>
                <div className="meter-sub">
                  {buyCount} vétel · {sellCount} eladás
                </div>
              </div>
              <div>
                <div className="meter-label">Lezárt pozíció</div>
                <div className="meter-value">{closedTrades.length}</div>
                <div className="meter-sub">
                  {closedTrades.length > 0 ? `${fmt((winCount / closedTrades.length) * 100, 0)}% nyereséges` : "még egy sem"}
                </div>
              </div>
              <div>
                <div className="meter-label">Díjak összesen</div>
                <div className="meter-value">{eur(totalFees)}</div>
                <div className="meter-sub">0,26% + csúszás</div>
              </div>
              <div>
                <div className="meter-label">Visszaesés a csúcstól</div>
                <div className="meter-value">{fmt(drawdownPct, 1)}%</div>
                <div className="bar">
                  <div
                    className="bar-fill"
                    style={{ width: `${Math.min((drawdownPct / (session.max_drawdown_pct || 20)) * 100, 100)}%` }}
                  />
                </div>
                <div className="meter-sub">leállítás {session.max_drawdown_pct ?? 20}%-nál</div>
              </div>
              <div>
                <div className="meter-label">Célösszeg</div>
                <div className="meter-value">{session.target_balance ? eur(session.target_balance, 0) : "nincs"}</div>
                {session.target_balance && latestSnapshot && (
                  <>
                    <div className="bar">
                      <div
                        className="bar-fill bar-fill-clay"
                        style={{ width: `${Math.min((latestSnapshot.total_value_eur / session.target_balance) * 100, 100)}%` }}
                      />
                    </div>
                    <div className="meter-sub">
                      {fmt((latestSnapshot.total_value_eur / session.target_balance) * 100, 0)}% megvan
                    </div>
                  </>
                )}
              </div>
            </div>

            {session.status === "risk_stopped" && (
              <div className="banner banner-danger">
                <p>
                  A bot automatikusan leállt: a portfólió elérte a vesztés-limitet ({session.max_drawdown_pct}%) a
                  csúcsértékéhez képest. Ez a tőkevédelem lépett közbe, nem te állítottad le.
                </p>
                <div className="banner-actions">
                  <button onClick={handleStop} disabled={loading}>
                    Session lezárása
                  </button>
                </div>
              </div>
            )}

            {session.status === "target_reached" && (
              <div className="banner banner-good">
                <p>
                  Célösszeg elérve ({eur(session.target_balance ?? 0)}). A bot leállt — döntsd el, mi legyen a pénzzel.
                </p>
                <div className="banner-actions">
                  <button onClick={handleStop} disabled={loading}>
                    Kivétel (session lezárása)
                  </button>
                  <input
                    type="number"
                    value={newTargetInput}
                    onChange={(e) => setNewTargetInput(Number(e.target.value))}
                    placeholder="Új célösszeg"
                  />
                  <button className="btn-primary" onClick={handleSetNewTarget} disabled={loading || newTargetInput <= 0}>
                    Új cél kitűzése, folytatás
                  </button>
                </div>
              </div>
            )}
          </section>

          {/* --------------------------------------------- coinonkénti helyzet */}
          <div className="section-head">
            <h2>Coinonkénti helyzet</h2>
            <span className="section-head-note">
              Oldalazón a Grid kereskedik, trendelőn a Trend/momentum — a bot coinonként külön dönt.
            </span>
          </div>
          <div className="grid grid-4">
            {TRADABLE_SYMBOLS.map((symbol) => {
              const asset = symbol.split("/")[0];
              return (
                <CoinCard
                  key={symbol}
                  symbol={symbol}
                  overview={overviewBySymbol[symbol]}
                  chart={chartData[symbol]}
                  regime={regimeBySymbol[symbol]}
                  plan={planBySymbol[symbol]}
                  qty={session.portfolio.holdings[asset] ?? 0}
                  avgCost={session.portfolio.cost_basis?.[asset] ?? 0}
                  trades={trades.filter((t) => t.symbol === symbol)}
                />
              );
            })}
          </div>

          {/* ------------------------------------------- mit csinált / mit nem */}
          <div className="grid grid-3" style={{ marginTop: 16 }}>
            <section className="card span-2">
              <div className="card-head">
                <div className="card-lead">Mit csinált a bot</div>
                <span className="small muted">{trades.length} kötés összesen</span>
              </div>
              <p className="card-note">
                Minden sor egy valódi kötés — mellette a mennyiség, az összeg és hogy mennyit hozott.
              </p>

              {recentTrades.length === 0 ? (
                <p className="muted">Még nincs kötés. A bot figyel, de eddig nem talált belépési pontot.</p>
              ) : (
                <>
                  <div className="trade-row row-head">
                    <div />
                    <div>MI TÖRTÉNT</div>
                    <div>MENNYISÉG / ÁR</div>
                    <div className="right">ÖSSZEG</div>
                    <div className="right">EREDMÉNY</div>
                    <div className="right">IDŐ</div>
                  </div>
                  {recentTrades.map((trade) => {
                    const isRisk = (trade.reason ?? "").startsWith("risk");
                    const digits = priceDigits(trade.symbol);
                    return (
                      <div className="trade-row row" key={trade.id}>
                        <span className={`icon-badge ${isRisk ? "icon-risk" : trade.side === "buy" ? "icon-buy" : "icon-sell"}`}>
                          {isRisk ? <IconRisk /> : trade.side === "buy" ? <IconBuy /> : <IconSell />}
                        </span>
                        <span className="trade-what">
                          {tradeSentence(trade)}
                          <span className="news-meta">{trade.reason ?? "—"}</span>
                        </span>
                        <span className="mono small muted">
                          {fmt(trade.qty, 6)}
                          <br />
                          {eur(trade.price, digits)}
                        </span>
                        <span className="mono right">{eur(trade.qty * trade.price)}</span>
                        <span className="right">
                          {trade.realized_pnl == null ? (
                            <span className="mono faint">—</span>
                          ) : (
                            <span className={`mono ${trade.realized_pnl >= 0 ? "pos" : "neg"}`}>
                              {signedEur(trade.realized_pnl)}
                              <br />
                              <span className="small" style={{ fontWeight: 400 }}>
                                {signedPct(trade.realized_pnl_pct ?? 0)}
                              </span>
                            </span>
                          )}
                        </span>
                        <span className="mono small faint right">{timeOfDay(parseTimestamp(trade.timestamp))}</span>
                      </div>
                    );
                  })}
                </>
              )}
            </section>

            <section className="card">
              <div className="card-lead">Amit nem csinált meg</div>
              <p className="card-note">
                Ezek a jelek megszülettek, de a rendszer visszatartotta őket. Összesen {blockedTotal} ilyen van a
                naplóban.
              </p>

              {blockedRanked.length === 0 ? (
                <p className="muted">Eddig egy jelet sem kellett visszatartani.</p>
              ) : (
                <>
                  <div className="bar-list">
                    {blockedRanked.map(([outcome, count]) => (
                      <div className="bar-item" key={outcome}>
                        <div className="bar-track">
                          <div
                            className={`bar-track-fill ${outcome === "blocked_sentiment_pause" ? "bar-track-fill-warn" : ""}`}
                            style={{ width: `${(count / blockedMax) * 100}%` }}
                          />
                        </div>
                        <span className="bar-label">{OUTCOME_LABELS[outcome as Decision["outcome"]] ?? outcome}</span>
                        <span className="bar-count">{count}</span>
                      </div>
                    ))}
                  </div>

                  <div className="blocked-list">
                    {recentBlocked.map((d, i) => (
                      <div className="blocked-item" key={i}>
                        <div className="blocked-item-top">
                          <span>
                            <strong>{d.symbol.split("/")[0]}</strong> {d.side === "buy" ? "vétel" : "eladás"} —{" "}
                            {STRATEGY_LABELS[d.strategy] ?? d.strategy}
                          </span>
                          <span className="mono small faint">{timeOfDay(parseTimestamp(d.timestamp))}</span>
                        </div>
                        <div className="blocked-item-why">{OUTCOME_LABELS[d.outcome]}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </section>
          </div>

          {/* --------------------------------------- stratégia-eredmény + pénz */}
          <div className="grid grid-3" style={{ marginTop: 16 }}>
            <section className="card span-2">
              <div className="card-lead">Melyik stratégia hozott pénzt</div>
              <p className="card-note">
                Az eredmény mindig ahhoz a stratégiához kerül, amelyik <em>lezárta</em> a pozíciót — így látszik, ha az
                egyik vásárol, a másik meg learatja.
              </p>

              {strategyPerf.length === 0 ? (
                <p className="muted">Még nincs lezárt kötés, amihez eredményt lehetne rendelni.</p>
              ) : (
                <>
                  <div className="strategy-row row-head">
                    <div>STRATÉGIA</div>
                    <div className="right">VÉTEL</div>
                    <div className="right">ELADÁS</div>
                    <div className="right">TALÁLAT</div>
                    <div className="right">REALIZÁLT</div>
                    <div />
                  </div>
                  {(() => {
                    const maxAbs = Math.max(...strategyPerf.map((s) => Math.abs(s.realized_pnl)), 0.0001);
                    return strategyPerf.map((s) => (
                      <div className="strategy-row row" key={s.strategy}>
                        <div>
                          <div className="strategy-name">{STRATEGY_LABELS[s.strategy] ?? s.strategy}</div>
                          <div className="strategy-desc">{STRATEGY_DESCRIPTIONS[s.strategy] ?? "—"}</div>
                        </div>
                        <div className="mono right">{s.buys}</div>
                        <div className="mono right">{s.sells}</div>
                        <div className="mono right">{s.win_rate_pct == null ? "—" : `${fmt(s.win_rate_pct, 0)}%`}</div>
                        <div className={`mono right ${s.realized_pnl >= 0 ? "pos" : "neg"}`}>{signedEur(s.realized_pnl)}</div>
                        <div style={{ paddingLeft: 14 }}>
                          <div className="bar" style={{ marginTop: 0, height: 8, borderRadius: 4 }}>
                            <div
                              className="bar-fill"
                              style={{
                                width: `${(Math.abs(s.realized_pnl) / maxAbs) * 100}%`,
                                background: s.realized_pnl >= 0 ? "var(--sage)" : "#c98a76",
                              }}
                            />
                          </div>
                        </div>
                      </div>
                    ));
                  })()}
                </>
              )}
            </section>

            <section className="card">
              <div className="card-lead">Miben áll a pénz</div>
              <p className="card-note">A készpénz az, amivel a bot még be tud szállni egy visszaesésbe.</p>

              <div className="cash-row">
                <span className="small muted">Szabad készpénz</span>
                <span className="cash-value">{eur(cash)}</span>
              </div>

              {portfolioTotal > 0 && (
                <div className="alloc-bar">
                  <div className="alloc-seg" style={{ width: `${(cash / portfolioTotal) * 100}%`, background: ALLOC_COLORS[0] }} />
                  {holdingRows.map((row, i) => (
                    <div
                      key={row.symbol}
                      className="alloc-seg"
                      style={{ width: `${(row.value / portfolioTotal) * 100}%`, background: ALLOC_COLORS[i + 1] }}
                    />
                  ))}
                </div>
              )}

              <div className="holding-row row-head" style={{ marginTop: 14 }}>
                <div />
                <div className="right">DARAB</div>
                <div className="right">ÉRTÉK</div>
                <div className="right">SÚLY</div>
              </div>
              {holdingRows.map((row) => (
                <div className="holding-row" key={row.symbol} style={{ borderBottom: "1px solid var(--hairline)" }}>
                  <span style={{ fontWeight: 600 }}>{row.asset}</span>
                  <span className="mono small muted right">{fmt(row.qty, 6)}</span>
                  <span className="mono right">{eur(row.value)}</span>
                  <span className="mono small muted right">
                    {portfolioTotal > 0 ? `${fmt((row.value / portfolioTotal) * 100, 0)}%` : "—"}
                  </span>
                </div>
              ))}
            </section>
          </div>

          {/* ------------------------------------------- rendelés-áramlás + hírek */}
          <div className="grid grid-3" style={{ marginTop: 16 }}>
            <section className="card span-2">
              <div className="card-head">
                <div className="card-lead">Vevői és eladói nyomás</div>
                <span className="tag tag-clay">Csak gyűjtjük</span>
              </div>
              <p className="card-note">
                A bot ezekre <strong>még nem kereskedik</strong> — előbb elég hosszú saját adatsor kell, amin le lehet
                tesztelni, hogy tényleg segítenek-e.
              </p>

              {flow.length === 0 ? (
                <p className="muted">Még nincs gyűjtött adat.</p>
              ) : (
                <div className="grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 22 }}>
                  <div>
                    <div className="small faint" style={{ marginBottom: 8 }}>
                      BTC — HALMOZOTT VÉTEL–ELADÁS KÜLÖNBSÉG
                    </div>
                    <Sparkline values={btcFlowSeries} />
                    <p className="small muted" style={{ marginTop: 8 }}>
                      {btcFlowSeries.length > 1 && btcFlowSeries[btcFlowSeries.length - 1] >= btcFlowSeries[0]
                        ? "Emelkedik: többen lépnek be vevőként, mint eladóként."
                        : "Csökken: az eladói oldal az aktívabb."}
                    </p>
                  </div>
                  <div>
                    <div className="flow-row row-head">
                      <div>COIN</div>
                      <div className="right">KÜLÖNBSÉG</div>
                      <div className="right">NYITOTT ÁLLOMÁNY</div>
                    </div>
                    {TRADABLE_SYMBOLS.map((symbol) => {
                      const row = latestFlow[symbol];
                      return (
                        <div className="flow-row" key={symbol} style={{ borderBottom: "1px solid var(--hairline)" }}>
                          <span style={{ fontWeight: 600 }}>{symbol.split("/")[0]}</span>
                          <span
                            className={`mono right ${!row ? "faint" : row.cumulative_volume_delta >= 0 ? "pos" : "neg"}`}
                          >
                            {row ? signed(row.cumulative_volume_delta, 1) : "—"}
                          </span>
                          <span className="mono right">
                            {row?.open_interest != null ? fmt(row.open_interest, 0) : "—"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </section>

            {newsCard}
          </div>

          {/* -------------------------------------------------- döntési napló */}
          <section className="card" style={{ marginTop: 16 }}>
            <div className="card-head">
              <div className="card-lead">Döntési napló</div>
              <label>
                <input
                  type="checkbox"
                  checked={onlyExecutedTrades}
                  onChange={(e) => setOnlyExecutedTrades(e.target.checked)}
                />
                Csak a ténylegesen megtörtént kötések (vétel és eladás)
              </label>
            </div>
            <p className="card-note">
              Nem csak a végrehajtott kötések — az is látszik, ha egy stratégia lépni akart, de a rendszer blokkolta vagy
              lecsökkentette a méretét.
            </p>

            {filteredDecisions.length === 0 ? (
              <p className="muted">
                {onlyExecutedTrades ? "Még nem történt tényleges kötés." : "Még nincs döntési esemény."}
              </p>
            ) : (
              <>
                <div className="decision-row row-head">
                  <div>IDŐ</div>
                  <div>COIN</div>
                  <div>STRATÉGIA</div>
                  <div>IRÁNY</div>
                  <div className="right">ÖSSZEG</div>
                  <div>KIMENETEL</div>
                </div>
                {filteredDecisions.slice(0, 30).map((d, i) => (
                  <div className="decision-row row" key={i}>
                    <span className="mono small faint">{timeWithSeconds(parseTimestamp(d.timestamp))}</span>
                    <span style={{ fontWeight: 600 }}>{d.symbol.split("/")[0]}</span>
                    <span className="small">{STRATEGY_LABELS[d.strategy] ?? d.strategy}</span>
                    <span className="small">{d.side === "buy" ? "vétel" : "eladás"}</span>
                    <span className="mono right small">
                      {d.qty != null && d.price != null ? eur(d.qty * d.price) : "—"}
                    </span>
                    <span className={`small ${OUTCOME_CLASS[d.outcome]}`}>
                      {OUTCOME_LABELS[d.outcome]}
                      {d.shrunk_pct ? ` (méret −${fmt(d.shrunk_pct, 0)}%)` : ""}
                    </span>
                  </div>
                ))}
              </>
            )}
          </section>

          {/* --------------------------------------------- részletes grafikonok */}
          <section className="card" style={{ marginTop: 16 }}>
            <div className="card-lead">Részletes grafikonok</div>
            <p className="card-note">
              Az elmúlt ~2 óra (240 tick) ára, volumene, RSI és MACD értéke. Ez csak a megjelenítést érinti — a
              stratégiák továbbra is a saját, rövidebb ablakukat használják a döntéshez.
            </p>
            {TRADABLE_SYMBOLS.map((symbol) =>
              chartData[symbol] ? (
                <CoinChart
                  key={symbol}
                  symbol={symbol}
                  data={chartData[symbol]}
                  trades={trades.filter((t) => t.symbol === symbol)}
                />
              ) : null,
            )}
          </section>
        </>
      )}
    </div>
  );
}

export default App;
