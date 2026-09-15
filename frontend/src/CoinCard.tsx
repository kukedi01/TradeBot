import {
  parseTimestamp,
  type CoinChartData,
  type MarketOverview,
  type RegimeEntry,
  type StrategyPlan,
  type Trade,
} from "./api";
import { eur, fmt, priceDigits, signedEur, signedPct } from "./format";
import { REGIME_LABELS, STRATEGY_LABELS } from "./labels";
import { Sparkline, type SparkMarker } from "./Sparkline";

function nearestIndex(timestamps: string[], targetMs: number): number {
  let bestIndex = 0;
  let bestDiff = Infinity;
  timestamps.forEach((t, i) => {
    const diff = Math.abs(parseTimestamp(t).getTime() - targetMs);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestIndex = i;
    }
  });
  return bestIndex;
}

export function CoinCard({
  symbol,
  overview,
  chart,
  regime,
  plan,
  qty,
  avgCost,
  trades,
}: {
  symbol: string;
  overview?: MarketOverview;
  chart?: CoinChartData;
  regime?: RegimeEntry;
  plan?: StrategyPlan;
  qty: number;
  avgCost: number;
  trades: Trade[];
}) {
  const digits = priceDigits(symbol);
  const series = chart?.prices ?? [];
  // Prefer the ticker price (fresh, and the same number the daily high/low
  // came from); fall back to the tail of the chart series if the overview
  // call failed for this coin.
  const price = overview?.price ?? (series.length > 0 ? series[series.length - 1] : null);

  const markers: SparkMarker[] =
    chart && chart.timestamps.length > 1
      ? trades
          .filter((t) => {
            const ts = parseTimestamp(t.timestamp).getTime();
            return (
              ts >= parseTimestamp(chart.timestamps[0]).getTime() &&
              ts <= parseTimestamp(chart.timestamps[chart.timestamps.length - 1]).getTime()
            );
          })
          .map((t) => ({
            index: nearestIndex(chart.timestamps, parseTimestamp(t.timestamp).getTime()),
            side: t.side === "buy" ? ("buy" as const) : ("sell" as const),
          }))
      : [];

  const high = overview?.daily_high ?? null;
  const low = overview?.daily_low ?? null;
  const hasRange = high !== null && low !== null && high > low && price !== null;
  const rangePos = hasRange ? Math.min(Math.max(((price! - low!) / (high! - low!)) * 100, 0), 100) : 0;

  const holdingValue = price !== null ? qty * price : 0;
  const hasPosition = qty > 0 && avgCost > 0 && price !== null;
  const unrealized = hasPosition ? (price! - avgCost) * qty : 0;

  const change = overview?.change_pct_24h ?? null;
  const regimeLabel = regime?.regime ? REGIME_LABELS[regime.regime] : null;
  const strategyLabel = regime?.active_strategy
    ? (STRATEGY_LABELS[regime.active_strategy] ?? regime.active_strategy)
    : null;

  return (
    <div className="coin-card">
      <div className="coin-card-top">
        <span className="coin-symbol">{symbol.split("/")[0]}</span>
        <span className="coin-price">{price === null ? "—" : eur(price, digits)}</span>
      </div>

      <div className="coin-change-row">
        <span>Ma</span>
        <span className={`mono ${change === null ? "faint" : change >= 0 ? "pos" : "neg"}`}>
          {change === null ? "—" : signedPct(change)}
        </span>
      </div>

      <Sparkline values={series} markers={markers} />

      {hasRange && (
        <div>
          <div className="coin-range-labels">
            <span>{fmt(low!, digits)}</span>
            <span>napi sáv</span>
            <span>{fmt(high!, digits)}</span>
          </div>
          <div className="coin-range-track">
            <div className="coin-range-mark" style={{ left: `calc(${rangePos}% - 1.5px)` }} />
          </div>
        </div>
      )}

      <div className="tags">
        {regimeLabel ? (
          <span className={`tag ${regime?.regime === "trending" ? "tag-clay" : "tag-plain"}`}>{regimeLabel}</span>
        ) : (
          <span className="tag tag-plain">Még figyeli…</span>
        )}
        {strategyLabel && <span className="tag tag-sage">{strategyLabel}</span>}
      </div>

      <div className="coin-foot">
        {qty <= 0 ? (
          <span>Most nincs nyitott pozíció.</span>
        ) : (
          <>
            Nyitva <strong>{eur(holdingValue)}</strong>
            {avgCost > 0 && <> · átlagár {eur(avgCost, digits)}</>}
            {hasPosition && (
              <div className={`mono small ${unrealized >= 0 ? "pos" : "neg"}`}>
                {signedEur(unrealized)} nem realizált
              </div>
            )}
          </>
        )}
      </div>

      {/* What the coin is actually waiting for. Without this the card shows
          a price near the bottom of its daily range and no trade, with no way
          to tell whether the bot is thinking, blocked, or broken. */}
      {plan && <CoinPlan plan={plan} price={price} digits={digits} />}
    </div>
  );
}

function CoinPlan({ plan, price, digits }: { plan: StrategyPlan; price: number | null; digits: number }) {
  const distance = (threshold: number) => (price === null ? null : ((threshold - price) / price) * 100);

  if (plan.rule === "grid" && (plan.next_buy_below !== null || plan.next_sell_above !== null)) {
    return (
      <div className="coin-plan">
        {plan.next_buy_below !== null && (
          <div className="coin-plan-row">
            <span className="coin-plan-dot" style={{ background: "var(--up)" }} />
            <span>
              Vétel <strong>{eur(plan.next_buy_below, digits)}</strong> alatt
              {distance(plan.next_buy_below) !== null && (
                <span className="faint"> ({signedPct(distance(plan.next_buy_below)!, 1)})</span>
              )}
            </span>
          </div>
        )}
        {plan.next_sell_above !== null && (
          <div className="coin-plan-row">
            <span className="coin-plan-dot" style={{ background: "var(--down)" }} />
            <span>
              Eladás <strong>{eur(plan.next_sell_above, digits)}</strong> fölött
              {distance(plan.next_sell_above) !== null && (
                <span className="faint"> ({signedPct(distance(plan.next_sell_above)!, 1)})</span>
              )}
            </span>
          </div>
        )}
      </div>
    );
  }

  if (plan.active_strategy === "trend_momentum") {
    return (
      <div className="coin-plan">
        <div className="coin-plan-row faint">Mozgóátlag-keresztezésre vár — ehhez nincs fix ár.</div>
      </div>
    );
  }

  if (plan.rule === "grid") {
    return (
      <div className="coin-plan">
        <div className="coin-plan-row faint">A sáv újrahangolása folyamatban.</div>
      </div>
    );
  }

  return null;
}
