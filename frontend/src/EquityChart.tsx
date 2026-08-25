import type { Snapshot } from "./api";

const WIDTH = 640;
const HEIGHT = 220;
const PADDING = 32;

function buildPath(values: number[], min: number, max: number): string {
  const range = max - min || 1;
  return values
    .map((value, i) => {
      const x = PADDING + (i / Math.max(values.length - 1, 1)) * (WIDTH - PADDING * 2);
      const y = HEIGHT - PADDING - ((value - min) / range) * (HEIGHT - PADDING * 2);
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

export function EquityChart({ snapshots }: { snapshots: Snapshot[] }) {
  if (snapshots.length < 2) {
    return <p>Még nincs elég adat a grafikonhoz — várj néhány tick-et.</p>;
  }

  const botValues = snapshots.map((s) => s.total_value_eur);
  const hodlValues = snapshots.map((s) => s.hodl_value_eur);
  const min = Math.min(...botValues, ...hodlValues);
  const max = Math.max(...botValues, ...hodlValues);

  const latestBot = botValues[botValues.length - 1];
  const latestHodl = hodlValues[hodlValues.length - 1];
  const diffPct = ((latestBot - latestHodl) / latestHodl) * 100;

  return (
    <div>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="equity-chart">
        <line x1={PADDING} y1={HEIGHT - PADDING} x2={WIDTH - PADDING} y2={HEIGHT - PADDING} className="chart-axis" />
        <line x1={PADDING} y1={PADDING} x2={PADDING} y2={HEIGHT - PADDING} className="chart-axis" />
        <path d={buildPath(hodlValues, min, max)} className="chart-line chart-line-hodl" />
        <path d={buildPath(botValues, min, max)} className="chart-line chart-line-bot" />
      </svg>
      <div className="chart-legend">
        <span>
          <span className="legend-swatch legend-bot" /> Bot: {latestBot.toFixed(2)} EUR
        </span>
        <span>
          <span className="legend-swatch legend-hodl" /> HODL: {latestHodl.toFixed(2)} EUR
        </span>
        <span className={diffPct >= 0 ? "sentiment-positive-text" : "sentiment-negative-text"}>
          {diffPct >= 0 ? "+" : ""}
          {diffPct.toFixed(2)}% a HODL-hoz képest
        </span>
      </div>
    </div>
  );
}
