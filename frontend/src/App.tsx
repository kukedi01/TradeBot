import { useEffect, useState } from "react";
import {
  getActiveSession,
  getDecisions,
  getNews,
  getRecommendation,
  getRegimeState,
  getSentiment,
  getSession,
  getSnapshots,
  getTrades,
  setTarget,
  startSession,
  stopAllSessions,
  stopSession,
  tickNow,
  type Decision,
  type NewsItem,
  type Recommendation,
  type RegimeEntry,
  type SentimentState,
  type Snapshot,
  type Trade,
  type TradingSession,
} from "./api";
import { EquityChart } from "./EquityChart";
import "./App.css";

const RISK_LABELS: Record<string, string> = {
  low: "Alacsony",
  medium: "Közepes",
  high: "Magas",
};

const REGIME_LABELS: Record<string, string> = {
  trending: "Trendelő piac",
  ranging: "Oldalazó piac",
};

const STRATEGY_LABELS: Record<string, string> = {
  grid: "Grid (sávkereskedés)",
  dca_rebalance: "DCA + rebalanszolás",
  trend_momentum: "Trend/momentum",
  risk: "Kockázatkezelés",
};

const OUTCOME_LABELS: Record<Decision["outcome"], string> = {
  executed: "Végrehajtva",
  blocked_inactive_strategy: "Blokkolva — nem az aktív stratégia",
  blocked_sentiment_pause: "Blokkolva — negatív hírhangulat",
  zero_after_sizing: "Elvetve — a méret nullára csökkent",
  stop_loss_triggered: "Stop-loss aktiválva",
};

const OUTCOME_CLASS: Record<Decision["outcome"], string> = {
  executed: "outcome-good",
  blocked_inactive_strategy: "outcome-muted",
  blocked_sentiment_pause: "outcome-warning",
  zero_after_sizing: "outcome-muted",
  stop_loss_triggered: "outcome-critical",
};

function sentimentColor(score: number): string {
  if (score <= -0.3) return "#f43f5e";
  if (score >= 0.3) return "#34d399";
  return "#fbbf24";
}

function App() {
  const [session, setSession] = useState<TradingSession | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);
  const [regimeState, setRegimeState] = useState<RegimeEntry[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
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

  useEffect(() => {
    getRecommendation(riskLevel).then(setRecommendation);
  }, [riskLevel]);

  const refresh = async (sessionId: number) => {
    const [updatedSession, updatedTrades, updatedRegime, updatedSnapshots, updatedDecisions] = await Promise.all([
      getSession(sessionId),
      getTrades(sessionId),
      getRegimeState(sessionId),
      getSnapshots(sessionId),
      getDecisions(sessionId),
    ]);
    setSession(updatedSession);
    setTrades(updatedTrades);
    setRegimeState(updatedRegime);
    setSnapshots(updatedSnapshots);
    setDecisions(updatedDecisions);
  };

  useEffect(() => {
    if (!session || session.status !== "running") return;
    const interval = setInterval(() => refresh(session.id), 5000);
    return () => clearInterval(interval);
  }, [session?.id, session?.status]);

  // On page load, reconnect to whatever session is still running on the
  // backend instead of showing an empty "start a session" screen for it.
  useEffect(() => {
    getActiveSession().then((active) => {
      if (active) refresh(active.id);
    });
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
    await refresh(session.id);
    setLoading(false);
  };

  const handleTick = async () => {
    if (!session) return;
    setLoading(true);
    await tickNow(session.id);
    await refresh(session.id);
    setLoading(false);
  };

  const handleSetNewTarget = async () => {
    if (!session) return;
    setLoading(true);
    await setTarget(session.id, newTargetInput);
    await refresh(session.id);
    setLoading(false);
  };

  return (
    <div className="dashboard">
      <div className="header-row">
        <h1>Kripto Paper Trading</h1>
        <button className="kill-switch" onClick={handleStopAll} disabled={loading}>
          🛑 Vészleállítás (minden session)
        </button>
      </div>

      <section className="panel">
        <h2>Piaci hangulat (hírek)</h2>
        {sentiment && (
          <p className="sentiment-summary">
            <span className="sentiment-dot" style={{ background: sentimentColor(sentiment.avg_sentiment) }} />
            Átlagos sentiment: <strong>{sentiment.avg_sentiment.toFixed(2)}</strong> ({sentiment.headline_count} hír) —{" "}
            {sentiment.pause_new_entries
              ? `⚠️ a bot most nem nyit új pozíciót (tétméret ×${sentiment.size_multiplier})`
              : "a bot normál üzemmódban kereskedik"}
          </p>
        )}
        {news.length === 0 ? (
          <p>Hírek betöltése…</p>
        ) : (
          <ul className="news-list">
            {news.map((item) => (
              <li key={item.link}>
                <span className="news-title">
                  <span className="sentiment-dot" style={{ background: sentimentColor(item.sentiment) }} />
                  <a href={item.link} target="_blank" rel="noreferrer">
                    {item.title}
                  </a>
                </span>
                <span className="news-meta">
                  {item.source} · {item.sentiment.toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {!session && (
        <section className="panel">
          <h2>Kockázati szint</h2>
          <div className="actions">
            {Object.entries(RISK_LABELS).map(([value, label]) => (
              <button
                key={value}
                onClick={() => setRiskLevel(value)}
                disabled={riskLevel === value}
              >
                {label}
              </button>
            ))}
          </div>

          {recommendation && (
            <div className="recommendation">
              <p>
                Ajánlott stratégia: <strong>{recommendation.recommended_strategy ?? "—"}</strong>
              </p>
              {recommendation.rationale.map((line, i) => (
                <p key={i} className="rationale">
                  {line}
                </p>
              ))}
              <table>
                <thead>
                  <tr>
                    <th>Stratégia</th>
                    <th>Hozam</th>
                    <th>Max visszaesés</th>
                    <th>Találati arány</th>
                    <th>Belefér a sávba?</th>
                  </tr>
                </thead>
                <tbody>
                  {recommendation.candidates.map((c) => (
                    <tr key={c.strategy_name}>
                      <td>{c.strategy_name}</td>
                      <td>{c.total_return_pct.toFixed(2)}%</td>
                      <td>{c.max_drawdown_pct.toFixed(2)}%</td>
                      <td>{c.win_rate_pct.toFixed(1)}%</td>
                      <td>{c.within_risk_band ? "igen" : "nem"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="actions">
            <label>
              Kezdő összeg (EUR):{" "}
              <input
                type="number"
                value={startingBalance}
                onChange={(e) => setStartingBalance(Number(e.target.value))}
              />
            </label>
          </div>

          <div className="actions">
            <label>
              <input type="checkbox" checked={useTarget} onChange={(e) => setUseTarget(e.target.checked)} />{" "}
              Célösszeg kitűzése
            </label>
            {useTarget && (
              <input
                type="number"
                value={targetInput}
                onChange={(e) => setTargetInput(Number(e.target.value))}
              />
            )}
          </div>

          <div className="actions">
            <label>
              Vesztés-limit (%):{" "}
              <input
                type="number"
                value={maxDrawdownInput}
                onChange={(e) => setMaxDrawdownInput(Number(e.target.value))}
              />
            </label>
          </div>
          <p className="rationale">
            Ha a portfólió értéke a valaha elért csúcsához képest ennyi %-ot esik, a bot automatikusan leáll — ez a
            stratégiától független tőkevédelem.
          </p>

          <p className="rationale">
            A bot coinonként (BTC, ETH, SOL, XRP) folyamatosan figyeli, hogy trendelő vagy oldalazó piacon vagyunk, és
            ez alapján automatikusan a legmegfelelőbb stratégiát választja — nincs kézi stratégiaválasztás.
          </p>

          <div className="actions">
            <button onClick={handleStart} disabled={loading}>
              Session indítása
            </button>
          </div>
        </section>
      )}

      {session && (
        <>
          <section className="panel">
            <h2>
              Session #{session.id} — {session.status} — {session.strategy_name}
            </h2>
            <p>Készpénz: {session.portfolio.cash_usd.toFixed(2)} EUR</p>
            {session.target_balance && <p>Célösszeg: {session.target_balance.toFixed(2)} EUR</p>}
            {session.max_drawdown_pct != null && <p>Vesztés-limit: {session.max_drawdown_pct}% a csúcsértéktől</p>}
            <p>
              Coinok:{" "}
              {Object.entries(session.portfolio.holdings).length === 0
                ? "—"
                : Object.entries(session.portfolio.holdings)
                    .map(([symbol, qty]) => `${qty.toFixed(6)} ${symbol}`)
                    .join(", ")}
            </p>

            {session.strategy_name === "auto" && regimeState.length > 0 && (
              <table>
                <thead>
                  <tr>
                    <th>Coin</th>
                    <th>Piaci helyzet</th>
                    <th>Aktív stratégia</th>
                  </tr>
                </thead>
                <tbody>
                  {regimeState.map((r) => (
                    <tr key={r.symbol}>
                      <td>{r.symbol}</td>
                      <td>{r.regime ? REGIME_LABELS[r.regime] : "még figyeli…"}</td>
                      <td>{r.active_strategy ? STRATEGY_LABELS[r.active_strategy] ?? r.active_strategy : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {session.status === "risk_stopped" && (
              <div className="target-reached risk-stopped">
                <p>
                  🛑 A bot automatikusan leállt: a portfólió a vesztés-limitet ({session.max_drawdown_pct}%) elérte a
                  csúcsértékéhez képest. Ez a tőkevédelem lépett közbe, nem te állítottad le.
                </p>
                <div className="actions">
                  <button onClick={handleStop} disabled={loading}>
                    Session lezárása
                  </button>
                </div>
              </div>
            )}

            {session.status === "target_reached" && (
              <div className="target-reached">
                <p>
                  🎯 Célösszeg elérve! ({session.target_balance?.toFixed(2)} EUR) A bot leállt, döntsd el, mi legyen a
                  pénzzel:
                </p>
                <div className="actions">
                  <button onClick={handleStop} disabled={loading}>
                    Kivétel (session lezárása)
                  </button>
                  <input
                    type="number"
                    value={newTargetInput}
                    onChange={(e) => setNewTargetInput(Number(e.target.value))}
                    placeholder="Új célösszeg (EUR)"
                  />
                  <button onClick={handleSetNewTarget} disabled={loading || newTargetInput <= 0}>
                    Új cél kitűzése, folytatás
                  </button>
                </div>
              </div>
            )}

            <div className="actions">
              <button onClick={handleTick} disabled={loading || session.status !== "running"}>
                Tick most
              </button>
              <button onClick={handleStop} disabled={loading || session.status === "stopped"}>
                Session leállítása
              </button>
            </div>
          </section>

          <section className="panel">
            <h2>Bot vs. HODL</h2>
            <EquityChart snapshots={snapshots} />
          </section>

          <section className="panel">
            <h2>Kötések</h2>
            {trades.length === 0 ? (
              <p>Még nincs kötés.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Idő</th>
                    <th>Szimbólum</th>
                    <th>Irány</th>
                    <th>Mennyiség</th>
                    <th>Ár</th>
                    <th>Összeg</th>
                    <th>Díj</th>
                    <th>Indoklás</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((trade) => (
                    <tr key={trade.id}>
                      <td>{new Date(trade.timestamp).toLocaleTimeString()}</td>
                      <td>{trade.symbol}</td>
                      <td>{trade.side}</td>
                      <td>{trade.qty.toFixed(6)}</td>
                      <td>{trade.price.toFixed(2)}</td>
                      <td>{(trade.qty * trade.price).toFixed(2)} EUR</td>
                      <td>{trade.fee.toFixed(2)}</td>
                      <td>{trade.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          <section className="panel">
            <h2>Döntési napló</h2>
            <p className="rationale">
              Nem csak a végrehajtott kötések — az is látszik, ha egy stratégia venni akart, de a rendszer blokkolta
              vagy lecsökkentette a méretét.
            </p>
            {decisions.length === 0 ? (
              <p style={{ marginTop: 12 }}>Még nincs döntési esemény.</p>
            ) : (
              <table style={{ marginTop: 12 }}>
                <thead>
                  <tr>
                    <th>Idő</th>
                    <th>Coin</th>
                    <th>Stratégia</th>
                    <th>Irány</th>
                    <th>Összeg</th>
                    <th>Kimenetel</th>
                    <th>Indoklás</th>
                  </tr>
                </thead>
                <tbody>
                  {decisions.slice(0, 30).map((d, i) => (
                    <tr key={i}>
                      <td>{new Date(d.timestamp).toLocaleTimeString()}</td>
                      <td>{d.symbol}</td>
                      <td>{STRATEGY_LABELS[d.strategy] ?? d.strategy}</td>
                      <td>{d.side}</td>
                      <td>{d.qty != null && d.price != null ? `${(d.qty * d.price).toFixed(2)} EUR` : "—"}</td>
                      <td className={OUTCOME_CLASS[d.outcome]}>
                        {OUTCOME_LABELS[d.outcome]}
                        {d.shrunk_pct ? ` (méret −${d.shrunk_pct}%)` : ""}
                      </td>
                      <td>{d.reason ?? d.detail ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}

export default App;
