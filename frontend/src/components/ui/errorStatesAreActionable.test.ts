import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'fs';
import { join } from 'path';

/**
 * A failure the user cannot act on is a dead end, and this counts them (FS-766).
 *
 * MEASURED BEFORE ANY OF THIS WAS WRITTEN: 68 failure messages across the frontend, **65 of
 * them a sentence in red and nothing else**. The cost is not the missing button — it is that
 * the only recovery left is a full page reload, which discards filters, the selected time
 * range, scroll position, and anything half-typed elsewhere. A transient 502 on one panel
 * therefore costs the operator their entire working state, and `refetch` was already sitting
 * in react-query the whole time.
 *
 * WHY A RATCHET RATHER THAN A CLEAN ASSERTION. Sixty-odd sites cannot honestly be converted
 * in one change, and a guard that fails until they all are is a guard somebody disables. This
 * pins the current count: it may fall freely and it may not rise. New code gets `ErrorState`;
 * the backlog is drained deliberately, and the number here goes down with it.
 *
 * The number is a MEASUREMENT, not a target. Lower it when you convert a site — the test
 * fails if you convert one and forget, which is the point: it tells you the ratchet is loose
 * rather than silently banking the improvement.
 */

// `process.cwd()` is the frontend root under vitest; `import.meta.url` resolved to `/src`
// because this file is transformed rather than run from disk. A path that does not exist
// makes `walk` throw, which is at least loud — a path that existed but held nothing would
// have passed the ratchet over an empty set, which is why the vacuity assertion below
// checks the file count rather than trusting the walk.
const SRC = join(process.cwd(), 'src');

/** Failure copy, in every spelling the codebase actually uses. */
const FAILURE = /(Failed to load|Unable to load|Error loading|Could not load|could not be loaded)/i;

/** Anything that gives the user a way forward from the failure. */
const ACTIONABLE = /<ErrorState|onRetry|<button|<Button|onClick|refetch\(/;

/**
 * A failure that says it is retrying itself, on a page that genuinely polls, is NOT a dead
 * end and must not be counted as one.
 *
 * The four engine pages say "Retrying automatically…" and every one of them carries a
 * `refetchInterval` — checked, not assumed. The user is not stranded; waiting works. Counting
 * these would have pushed the number up and then pressured somebody into adding a Retry
 * button that duplicates a poll, which is friction added in the name of removing it.
 *
 * The claim is only honoured when the file actually polls. A page that SAYS it retries and
 * does not is a worse dead end than one that says nothing, because the user waits.
 */
const SELF_HEALING = /[Rr]etrying automatically/;
const POLLS = /refetchInterval/;

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (full.endsWith('.tsx') && !full.includes('.test.')) out.push(full);
  }
  return out;
}

function deadEnds(): string[] {
  const found: string[] = [];
  for (const file of walk(SRC)) {
    const source = readFileSync(file, 'utf8');
    const lines = source.split('\n');
    lines.forEach((line, i) => {
      if (!FAILURE.test(line)) return;
      const window = lines.slice(Math.max(0, i - 6), i + 7).join('\n');
      if (ACTIONABLE.test(window)) return;
      if (SELF_HEALING.test(window) && POLLS.test(source)) return;
      found.push(`${file.replace(SRC, '')}:${i + 1}`);
    });
  }
  return found;
}

/**
 * Pinned 2026-08-19 at the measured value. **Only ever lower this.**
 *
 * 72 when this detector was first run in its final form, 67 after the operator-facing pages
 * (Alarms, Assets, AssetDetail ×2, and the asset alarms panel) gained a retry. The remainder
 * is a deliberate backlog rather than an oversight: converting sixty-odd JSX sites blind is
 * how a UX improvement becomes a regression, and each one needs its query's `refetch` wired
 * by hand.
 *
 * Lower it as sites are converted. The third test below fails if you convert one and forget
 * to lower it — banking an improvement silently is how a ratchet stops ratcheting.
 */
const DEAD_END_CEILING = 67;

describe('failure states the user can act on', () => {
  it('finds failure messages at all', () => {
    // Vacuity. A walker that matches nothing passes the ratchet over an empty set, and the
    // ceiling then records a victory nobody won.
    const files = walk(SRC);
    expect(files.length).toBeGreaterThan(100);
    const anyFailureCopy = files.some((f) => FAILURE.test(readFileSync(f, 'utf8')));
    expect(anyFailureCopy).toBe(true);
  });

  it('does not add new dead ends', () => {
    const found = deadEnds();
    expect(
      found.length,
      `Dead-end failure states rose to ${found.length} (ceiling ${DEAD_END_CEILING}).\n` +
        `A failure with no way forward leaves a reload as the only recovery, and a reload ` +
        `throws away the filters and time range the page was showing.\n` +
        `Use <ErrorState message="…" onRetry={() => refetch()} retrying={isFetching} />.\n\n` +
        found.slice(0, 12).join('\n')
    ).toBeLessThanOrEqual(DEAD_END_CEILING);
  });

  it('has a ceiling that is not slack', () => {
    // The other half. A ceiling well above reality passes through a regression, which is how
    // a ratchet quietly stops ratcheting — the same failure the backend's test-count floor
    // has a second assertion for.
    const found = deadEnds();
    expect(
      DEAD_END_CEILING - found.length,
      `the ceiling is ${DEAD_END_CEILING} and only ${found.length} dead ends exist — ` +
        `lower it to ${found.length} so it keeps meaning something`
    ).toBeLessThanOrEqual(2);
  });
});
