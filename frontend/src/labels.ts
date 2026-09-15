import type { Decision } from "./api";

export const REGIME_LABELS: Record<string, string> = {
  trending: "Trendelő",
  ranging: "Oldalazó",
};

export const STRATEGY_LABELS: Record<string, string> = {
  grid: "Grid",
  dca_rebalance: "DCA + rebalanszolás",
  trend_momentum: "Trend/momentum",
  risk: "Kockázatkezelés",
  unknown: "Ismeretlen",
};

// What each strategy actually does, in one clause -- shown next to its name
// so the performance table doesn't assume you remember the vocabulary.
export const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  grid: "Lent vesz, fent ad el a sávban",
  dca_rebalance: "Ütemezett vétel, elcsúszáskor rebalanszol",
  trend_momentum: "Felszáll a tartós mozgásra",
  risk: "Stop-loss, a stratégiáktól függetlenül",
};

export const OUTCOME_LABELS: Record<Decision["outcome"], string> = {
  executed: "Végrehajtva",
  blocked_inactive_strategy: "Nem az aktív stratégia",
  blocked_4h_downtrend: "A 4 órás trend nem erősíti meg",
  blocked_not_position_owner: "Nem ő nyitotta a pozíciót",
  blocked_handoff_below_cost_basis: "Az átvétel a bekerülési ár alatt lenne",
  blocked_sentiment_pause: "Negatív hírhangulat",
  zero_after_sizing: "A méret nullára csökkent",
  stop_loss_triggered: "Stop-loss aktiválva",
};

export const OUTCOME_CLASS: Record<Decision["outcome"], string> = {
  executed: "outcome-good",
  blocked_inactive_strategy: "outcome-muted",
  blocked_4h_downtrend: "outcome-muted",
  blocked_not_position_owner: "outcome-muted",
  blocked_handoff_below_cost_basis: "outcome-muted",
  blocked_sentiment_pause: "outcome-warning",
  zero_after_sizing: "outcome-muted",
  stop_loss_triggered: "outcome-critical",
};

export function sentimentColor(score: number): string {
  if (score <= -0.3) return "var(--down)";
  if (score >= 0.3) return "var(--up)";
  return "var(--warn)";
}
