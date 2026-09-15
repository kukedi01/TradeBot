import { parseTimestamp, type Snapshot } from "./api";
import { eur, fmt, signedPct } from "./format";

const WIDTH = 700;
const HEIGHT = 240;
const LEFT = 46;
const TOP = 12;
const BOTTOM = 28;

// Points are placed by actual elapsed time, not by array index. The
// snapshots endpoint returns dense recent history (full tick resolution for
// the last 6h) next to sparse older history (thinned to one point per
// bucket) -- spacing by index would let the dense tail eat almost the whole
// chart width regardless of how many days/months the older, sparse part
// actually spans, which is exactly the distortion this used to show on the
// month/half-year/year views.
function buildPoints(
  snapshots: Snapshot[],
  key: "total_value_eur" | "hodl_value_eur",
  tMin: number,
  tMax: number,
  vMin: number,
  vMax: number,
): string {
  const tRange = tMax - tMin || 1;
  const vRange = vMax - vMin || 1;
  const plotHeight = HEIGHT - TOP - BOTTOM;
  return snapshots
    .map((s) => {
      const t = parseTimestamp(s.timestamp).getTime();
      const x = LEFT + ((t - tMin) / tRange) * (WIDTH - LEFT);
      const y = TOP + plotHeight - ((s[key] - vMin) / vRange) * plotHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

// Short spans get a time-of-day label, longer ones a date -- a "13:42" label
// is useless on a year view and a full date is noise on an hour view.
function axisLabel(date: Date, spanMs: number): string {
  if (spanMs <= 36 * 3600 * 1000) {
    return date.toLocaleTimeString("hu-HU", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("hu-HU", { month: "short", day: "numeric" });
}

export function EquityChart({ snapshots }: { snapshots: Snapshot[] }) {
  if (snapshots.length < 2) {
    return <p className="muted">Még nincs elég adat a grafikonhoz — várj néhány tick-et.</p>;
  }

  const botValues = snapshots.map((s) => s.total_value_eur);
  const hodlValues = snapshots.map((s) => s.hodl_value_eur);
  const min = Math.min(...botValues, ...hodlValues);
  const max = Math.max(...botValues, ...hodlValues);

  const tMin = parseTimestamp(snapshots[0].timestamp).getTime();
  const tMax = parseTimestamp(snapshots[snapshots.length - 1].timestamp).getTime();
  const spanMs = tMax - tMin || 1;

  const latestBot = botValues[botValues.length - 1];
  const latestHodl = hodlValues[hodlValues.length - 1];
  const diffPct = ((latestBot - latestHodl) / latestHodl) * 100;

  const plotHeight = HEIGHT - TOP - BOTTOM;
  const gridValues = [max, (max + min) / 2, min];
  const yFor = (value: number) => TOP + plotHeight - ((value - min) / (max - min || 1)) * plotHeight;

  const botPoints = buildPoints(snapshots, "total_value_eur", tMin, tMax, min, max);
  const hodlPoints = buildPoints(snapshots, "hodl_value_eur", tMin, tMax, min, max);

  return (
    <div>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="equity-chart">
        {gridValues.map((value, i) => (
          <g key={i}>
            <line x1={LEFT} x2={WIDTH} y1={yFor(value)} y2={yFor(value)} className="chart-grid-line" />
            <text x={0} y={yFor(value) + 4} className="chart-label">
              {fmt(value, 0)}
            </text>
          </g>
        ))}
        <polyline points={hodlPoints} className="chart-line chart-line-hodl" />
        <polyline points={botPoints} className="chart-line chart-line-bot" />
        <circle cx={WIDTH} cy={yFor(latestBot)} r={5} fill="var(--sage)" />
        <circle cx={WIDTH} cy={yFor(latestHodl)} r={4} fill="var(--neutral-line)" />

        {/* Time axis -- start and end of the visible window, so it's clear
            how much real time the line actually spans. */}
        <text x={LEFT} y={HEIGHT - 6} className="chart-label">
          {axisLabel(new Date(tMin), spanMs)}
        </text>
        <text x={WIDTH} y={HEIGHT - 6} textAnchor="end" className="chart-label">
          {axisLabel(new Date(tMax), spanMs)}
        </text>
      </svg>
      <div className="chart-legend">
        <span>
          <span className="legend-swatch legend-bot" /> A bot: {eur(latestBot)}
        </span>
        <span>
          <span className="legend-swatch legend-hodl" /> Sima tartás: {eur(latestHodl)}
        </span>
        <span className={diffPct >= 0 ? "pos" : "neg"}>{signedPct(diffPct)} a tartáshoz képest</span>
      </div>
    </div>
  );
}
