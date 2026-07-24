/**
 * Chart palette — validated, not eyeballed.
 *
 * The `opsgrid-*` design tokens are neutral (greys), so charts need their own
 * colors. Every value below was checked with the data-viz validator against the
 * app's ACTUAL chart surface (`--color-panel`: #ffffff light, #171717 dark),
 * not a generic surface:
 *
 *   categorical (blue, orange)  light #2a78d6/#eb6834 — ALL CHECKS PASS
 *                               dark  #3987e5/#d95926 — ALL CHECKS PASS
 *   severity ordinal ramp       ALL CHECKS PASS in both modes (--ordinal)
 *
 * A first attempt used the four reserved status colors for alarm severity; the
 * validator FAILED it — status `warning` (#fab219) and `serious` (#ec835a) are
 * only ΔE 13.6 apart to normal vision, below the hard floor of 15, so stacked
 * segments would have been indistinguishable to everyone. Severity is an
 * ORDINAL scale (low → critical), and the correct form for that is a single-hue
 * sequential ramp — which is what this is. Don't swap it back to status hues.
 *
 * Dark steps are selected for the dark surface, not an automatic flip.
 */
export type ChartTheme = 'light' | 'dark';

export interface ChartPalette {
  /** Categorical slot 1 — also the single-series/sequential default. */
  series1: string;
  /** Categorical slot 2. */
  series2: string;
  /** Ordinal severity ramp, lightest (least severe) → darkest (most severe). */
  severityRamp: [string, string, string, string];
  grid: string;
  axis: string;
  mutedText: string;
}

const LIGHT: ChartPalette = {
  series1: '#2a78d6',
  series2: '#eb6834',
  severityRamp: ['#f0a3a3', '#dd6a6a', '#c93a3a', '#9b2020'],
  grid: '#e1e0d9',
  axis: '#c3c2b7',
  mutedText: '#898781',
};

const DARK: ChartPalette = {
  series1: '#3987e5',
  series2: '#d95926',
  // The ramp validated in both modes, so it is shared deliberately.
  severityRamp: ['#f0a3a3', '#dd6a6a', '#c93a3a', '#9b2020'],
  grid: '#2c2c2a',
  axis: '#383835',
  mutedText: '#898781',
};

export function chartPalette(theme: ChartTheme): ChartPalette {
  return theme === 'dark' ? DARK : LIGHT;
}

/**
 * Map an alarm severity to its ramp step. Severity is ordinal, so the ramp is
 * indexed by rank rather than by hue-per-name; unknown severities fall to the
 * lightest step instead of inventing a color.
 */
const SEVERITY_RANK: Record<string, number> = {
  low: 0,
  info: 0,
  minor: 0,
  medium: 1,
  moderate: 1,
  warning: 1,
  high: 2,
  major: 2,
  critical: 3,
  severe: 3,
};

export function severityColor(severity: string, palette: ChartPalette): string {
  const rank = SEVERITY_RANK[severity?.toLowerCase()] ?? 0;
  return palette.severityRamp[rank];
}

/** Severities ordered least → most severe, so stacks read consistently. */
export function orderSeverities(severities: string[]): string[] {
  return [...severities].sort(
    (a, b) =>
      (SEVERITY_RANK[a?.toLowerCase()] ?? 0) - (SEVERITY_RANK[b?.toLowerCase()] ?? 0),
  );
}
