/** Layout and type tuned for floor supervisors: gloves, quick glances, large taps. */
export const HIT = {
  /** Minimum height for primary tap targets (RN accessibility guideline ~44–48; we go larger). */
  button: 60,
  row: 56,
  tab: 52,
} as const;

export const PAD = {
  screen: 20,
  card: 18,
  gap: 14,
} as const;

export const TYPE = {
  hero: 30,
  title: 24,
  section: 20,
  body: 18,
  label: 16,
  stat: 44,
  small: 15,
} as const;
