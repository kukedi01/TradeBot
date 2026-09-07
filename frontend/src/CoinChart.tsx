import { useState } from "react";
import { getDailyRange, type CoinChartData, type Trade } from "./api";

const WIDTH = 640;
const PADDING = 30;
const PRICE_H = 90;
const VOLUME_H = 26;
const RSI_H = 46;
const MACD_H = 56;
const GAP = 16;

const PRICE_Y = 0;
const VOLUME_Y = PRICE_H + 6;
const RSI_Y = VOLUME_Y + VOLUME_H + GAP;
const MACD_Y = RSI_Y + RSI_H + GAP;
const TOTAL_HEIGHT = MACD_Y + MACD_H + 4;

function nonNull(values: (number | null)[]): number[] {
  return values.filter((v): v is number => v !== null);
}

function xFor(i: number, n: number): number {
  return PADDING + (i / Math.max(n - 1, 1)) * (WIDTH - PADDING * 2);
}

function yFor(value: number, min: number, max: number, yTop: number, height: number): number {
  const range = max - min || 1;
  return yTop + height - ((value - min) / range) * height;
}

// Chart only ever holds the session's own short rolling window (~30 ticks),
// so a linear scan to find the closest sample for a trade's timestamp is
// cheap -- no need for a binary search.
function nearestIndex(timestamps: string[], targetMs: number): number {
  let bestIndex = 0;
  let bestDiff = Infinity;
  timestamps.forEach((t, i) => {
    const diff = Math.abs(new Date(t).getTime() - targetMs);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestIndex = i;
    }
  });
  return bestIndex;
}

const MARKER_OFFSET = 9;

function linePath(values: (number | null)[], min: number, max: number, yTop: number, height: number): string {
  const range = max - min || 1;
  let path = "";
  let started = false;
  values.forEach((v, i) => {
    if (v === null) {
      started = false;
      return;
    }
    const x = xFor(i, values.length);
    const y = yTop + height - ((v - min) / range) * height;
    path += `${started ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)} `;
    started = true;
  });
  return path.trim();
}

type DailyRangeState = { status: "loading" } | { status: "error" } | { status: "loaded"; high: number; low: number };

export function CoinChart({ symbol, data, trades }: { symbol: string; data: CoinChartData; trades: Trade[] }) {
  const [dailyRange, setDailyRange] = useState<DailyRangeState | null>(null);

  if (data.prices.length < 2) {
    return (
      <div className="coin-chart-empty">
        <strong>{symbol}</strong> — még gyűlik az adat (kell pár tick).
      </div>
    );
  }

  function handlePriceClick() {
    setDailyRange({ status: "loading" });
    getDailyRange(symbol)
      .then((r) => setDailyRange({ status: "loaded", high: r.high, low: r.low }))
      .catch(() => setDailyRange({ status: "error" }));
  }

  const prices = data.prices;
  const priceMin = Math.min(...prices);
  const priceMax = Math.max(...prices);
  const latestPrice = prices[prices.length - 1];

  // Only trades that actually fall inside this chart's own rolling window
  // get a marker -- an older trade has already scrolled out of the ~30-tick
  // history the strategies themselves are looking at.
  const windowStart = new Date(data.timestamps[0]).getTime();
  const windowEnd = new Date(data.timestamps[data.timestamps.length - 1]).getTime();
  const markers = trades
    .filter((t) => {
      const ts = new Date(t.timestamp).getTime();
      return ts >= windowStart && ts <= windowEnd;
    })
    .map((t) => {
      const index = nearestIndex(data.timestamps, new Date(t.timestamp).getTime());
      const x = xFor(index, prices.length);
      const y = yFor(prices[index], priceMin, priceMax, PRICE_Y, PRICE_H);
      return { ...t, x, y };
    });

  const volumes = data.volumes;
  const volumeMax = Math.max(...volumes, 1);
  const barWidth = (WIDTH - PADDING * 2) / Math.max(volumes.length, 1);

  const rsiValues = nonNull(data.rsi);
  const hasRsi = rsiValues.length > 0;
  const latestRsi = hasRsi ? data.rsi[data.rsi.length - 1] : null;

  const macdValues = nonNull(data.macd);
  const signalValues = nonNull(data.macd_signal);
  const hasMacd = macdValues.length > 0;
  const macdAll = [...macdValues, ...signalValues, ...nonNull(data.macd_histogram)];
  const macdAbsMax = macdAll.length > 0 ? Math.max(...macdAll.map(Math.abs), 0.0001) : 0.0001;

  return (
    <div className="coin-chart">
      <div className="coin-chart-header">
        <strong>{symbol}</strong>
        <span className="coin-chart-price">{latestPrice.toFixed(4)} EUR</span>
        {hasRsi && latestRsi !== null && (
          <span className={latestRsi >= 70 ? "outcome-critical" : latestRsi <= 30 ? "outcome-good" : "outcome-muted"}>
            RSI {latestRsi.toFixed(0)}
          </span>
        )}
      </div>
      <svg viewBox={`0 0 ${WIDTH} ${TOTAL_HEIGHT}`} className="coin-chart-svg">
        {/* Price */}
        <path d={linePath(prices, priceMin, priceMax, PRICE_Y, PRICE_H)} className="chart-line chart-line-bot" />
        <text x={WIDTH - PADDING} y={PRICE_Y + 9} textAnchor="end" className="chart-label">
          {priceMax.toFixed(4)}
        </text>
        <text x={WIDTH - PADDING} y={PRICE_Y + PRICE_H - 2} textAnchor="end" className="chart-label">
          {priceMin.toFixed(4)}
        </text>

        {/* Click anywhere on the price area to fetch today's real Kraken
            high/low -- separate from priceMin/priceMax above, which are just
            the min/max of this chart's own short rolling window. */}
        <rect
          x={PADDING}
          y={PRICE_Y}
          width={WIDTH - PADDING * 2}
          height={PRICE_H}
          fill="transparent"
          style={{ cursor: "pointer" }}
          onClick={handlePriceClick}
        >
          <title>Kattints a mai napi maximum/minimum árért</title>
        </rect>
        {dailyRange && (
          <g onClick={() => setDailyRange(null)} style={{ cursor: "pointer" }}>
            <rect x={PADDING} y={PRICE_Y + 4} width={150} height={dailyRange.status === "loaded" ? 34 : 18} className="daily-range-box" />
            {dailyRange.status === "loading" && (
              <text x={PADDING + 6} y={PRICE_Y + 16} className="chart-label">
                Betöltés…
              </text>
            )}
            {dailyRange.status === "error" && (
              <text x={PADDING + 6} y={PRICE_Y + 16} className="chart-label">
                Nem sikerült lekérni
              </text>
            )}
            {dailyRange.status === "loaded" && (
              <>
                <text x={PADDING + 6} y={PRICE_Y + 16} className="chart-label">
                  Napi max: {dailyRange.high.toFixed(4)} EUR
                </text>
                <text x={PADDING + 6} y={PRICE_Y + 30} className="chart-label">
                  Napi min: {dailyRange.low.toFixed(4)} EUR
                </text>
              </>
            )}
          </g>
        )}

        {/* Trade markers -- triangle pointing at the price point from the
            side that reads naturally: buys push up from below, sells press
            down from above. */}
        {markers.map((m, i) =>
          m.side === "buy" ? (
            <polygon
              key={`${m.id}-${i}`}
              points={`${m.x},${m.y + 3} ${m.x - 5},${m.y + MARKER_OFFSET} ${m.x + 5},${m.y + MARKER_OFFSET}`}
              className="chart-marker-buy"
            >
              <title>{`Vétel — ${m.qty.toFixed(6)} @ ${m.price.toFixed(4)} EUR`}</title>
            </polygon>
          ) : (
            <polygon
              key={`${m.id}-${i}`}
              points={`${m.x},${m.y - 3} ${m.x - 5},${m.y - MARKER_OFFSET} ${m.x + 5},${m.y - MARKER_OFFSET}`}
              className="chart-marker-sell"
            >
              <title>{`Eladás — ${m.qty.toFixed(6)} @ ${m.price.toFixed(4)} EUR`}</title>
            </polygon>
          ),
        )}

        {/* Volume */}
        {volumes.map((v, i) => {
          const h = (v / volumeMax) * VOLUME_H;
          return (
            <rect
              key={i}
              x={xFor(i, volumes.length) - barWidth / 2.4}
              y={VOLUME_Y + VOLUME_H - h}
              width={barWidth / 1.2}
              height={h}
              className="volume-bar"
            />
          );
        })}
        <text x={PADDING} y={VOLUME_Y - 4} className="chart-label">
          Volumen (tick közötti)
        </text>

        {/* RSI */}
        <text x={PADDING} y={RSI_Y - 4} className="chart-label">
          RSI (14)
        </text>
        {hasRsi && (
          <>
            <line
              x1={PADDING}
              x2={WIDTH - PADDING}
              y1={RSI_Y + RSI_H - (70 / 100) * RSI_H}
              y2={RSI_Y + RSI_H - (70 / 100) * RSI_H}
              className="chart-ref-line"
            />
            <line
              x1={PADDING}
              x2={WIDTH - PADDING}
              y1={RSI_Y + RSI_H - (30 / 100) * RSI_H}
              y2={RSI_Y + RSI_H - (30 / 100) * RSI_H}
              className="chart-ref-line"
            />
            <path d={linePath(data.rsi, 0, 100, RSI_Y, RSI_H)} className="chart-line chart-line-rsi" />
          </>
        )}

        {/* MACD */}
        <text x={PADDING} y={MACD_Y - 4} className="chart-label">
          MACD (6/13/5)
        </text>
        {hasMacd && (
          <>
            <line
              x1={PADDING}
              x2={WIDTH - PADDING}
              y1={MACD_Y + MACD_H / 2}
              y2={MACD_Y + MACD_H / 2}
              className="chart-axis"
            />
            {data.macd_histogram.map((v, i) => {
              if (v === null) return null;
              const zeroY = MACD_Y + MACD_H / 2;
              const h = (Math.abs(v) / macdAbsMax) * (MACD_H / 2);
              return (
                <rect
                  key={i}
                  x={xFor(i, data.macd_histogram.length) - barWidth / 2.4}
                  y={v >= 0 ? zeroY - h : zeroY}
                  width={barWidth / 1.2}
                  height={h}
                  className={v >= 0 ? "macd-hist-pos" : "macd-hist-neg"}
                />
              );
            })}
            <path
              d={linePath(
                data.macd.map((v) => (v === null ? null : v)),
                -macdAbsMax,
                macdAbsMax,
                MACD_Y,
                MACD_H,
              )}
              className="chart-line chart-line-bot"
            />
            <path
              d={linePath(data.macd_signal, -macdAbsMax, macdAbsMax, MACD_Y, MACD_H)}
              className="chart-line chart-line-hodl"
            />
          </>
        )}
      </svg>
    </div>
  );
}
