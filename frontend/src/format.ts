// Hungarian number formatting in one place: space as thousands separator,
// comma as decimal separator. Doing this per-call with toFixed() is what made
// the old UI read like a log file instead of a dashboard.

export function fmt(value: number, digits = 2): string {
  return value.toLocaleString("hu-HU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function eur(value: number, digits = 2): string {
  return `${fmt(value, digits)} €`;
}

export function signedEur(value: number, digits = 2): string {
  return `${value >= 0 ? "+" : ""}${fmt(value, digits)} €`;
}

export function signedPct(value: number, digits = 2): string {
  return `${value >= 0 ? "+" : ""}${fmt(value, digits)}%`;
}

// A signed number with no unit -- sentiment scores and the cumulative volume
// delta are both "which way and how much", but neither is a percentage.
export function signed(value: number, digits = 2): string {
  return `${value >= 0 ? "+" : ""}${fmt(value, digits)}`;
}

// XRP trades around 1 EUR, BTC around 90 000 -- two decimals is unreadable
// for one and excessive for the other.
export function priceDigits(symbol: string): number {
  return symbol.startsWith("XRP") ? 4 : 2;
}

export function timeOfDay(date: Date): string {
  return date.toLocaleTimeString("hu-HU", { hour: "2-digit", minute: "2-digit" });
}

export function timeWithSeconds(date: Date): string {
  return date.toLocaleTimeString("hu-HU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
