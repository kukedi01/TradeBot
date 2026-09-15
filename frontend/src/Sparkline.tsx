const WIDTH = 300;
const HEIGHT = 66;
const MARKER_GAP = 8;

export interface SparkMarker {
  index: number;
  side: "buy" | "sell";
}

/** A small, axis-free price line for the per-coin cards: just the shape of
 *  the recent move plus where the bot actually traded. The detailed chart
 *  (volume, RSI, MACD) lives further down the page in CoinChart. */
export function Sparkline({ values, markers = [] }: { values: number[]; markers?: SparkMarker[] }) {
  if (values.length < 2) {
    return <div className="small faint">Még gyűlik az adat…</div>;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const x = (i: number) => (i / (values.length - 1)) * WIDTH;
  // 6px of padding top and bottom so the line never touches the edge and the
  // trade markers have somewhere to sit.
  const y = (v: number) => HEIGHT - 6 - ((v - min) / range) * (HEIGHT - 12);

  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="sparkline">
      <polyline points={points} fill="none" stroke="var(--sage)" strokeWidth="2" strokeLinejoin="round" />
      {markers.map((m, i) => {
        const mx = x(m.index);
        const my = y(values[m.index]);
        // Buys push up from below the line, sells press down from above --
        // the same reading as the detailed chart's markers.
        return m.side === "buy" ? (
          <path
            key={i}
            d={`M ${mx} ${my + 3} l 4.5 ${MARKER_GAP} h -9 z`}
            fill="var(--up)"
          />
        ) : (
          <path
            key={i}
            d={`M ${mx} ${my - 3} l 4.5 ${-MARKER_GAP} h -9 z`}
            fill="var(--down)"
          />
        );
      })}
    </svg>
  );
}
