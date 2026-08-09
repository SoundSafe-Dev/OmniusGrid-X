/**
 * Three frontend safety surfaces that may only shrink (FS-554 / FS-555 / FS-556).
 *
 * Each is a population where most instances are fine, a few are defects, and telling them
 * apart needs judgement a sweep cannot supply. A file demanding thirty fixes gets argued with
 * and ignored; a number that can only move one way costs nothing to keep and makes the next
 * addition a decision.
 *
 * ## Non-null assertions — 30, only down
 *
 * `foo!` tells the compiler to stop checking. Most of these are correct and TypeScript simply
 * cannot see it: `carrier.insuranceExpiry!` sits inside a `.map()` over a list already
 * `.filter()`ed on that field, and narrowing does not cross a callback boundary. The plan
 * listed "twelve on nullable network fields"; measuring found that all but one were guarded
 * by a preceding filter or ternary.
 *
 * **The one that was real is the sharpest possible example.** `GeofencingPanel` renders
 * `(selectedZone.radius! / 1000).toFixed(1)` — and that file's own header records that
 * `zone.center!.latitude` threw on the first centerless zone and, with only the app-root
 * ErrorBoundary, **blanked the entire app**. `radius` is optional for exactly the same reason
 * (a polygon zone has neither), so this is the identical crash on the sibling field, twenty
 * lines below the comment describing it. Fixed by omitting the row rather than rendering NaN.
 *
 * ## Inline `toLocale*` — 93, only down
 *
 * `utils/formatters.ts` wraps every date and number conversion in a try/catch returning
 * `'Invalid date'`. Ninety-three call sites bypass it, so `new Date(null).toLocaleString()`
 * renders the literal string **"Invalid Date"** to a user, and a malformed timestamp from an
 * ERP feed becomes a cell of nonsense rather than a handled absence.
 *
 * Paired with a FLOOR on `formatters` usage (65), for the reason the swallow ratchet gives:
 * a cap on the bad number alone is satisfied by deleting a call site, and only moving both
 * together means a conversion was actually migrated.
 *
 * ## Status-colour maps — 12 files, only down
 *
 * Twelve files map a status to a colour. `STATUS_COLORS` in `utils/constants.ts` has a
 * contrast test protecting its values; eleven copies do not, and `pages/Alarms.tsx` reproduces
 * `STATUS_COLORS` verbatim including the exact strings that test exists to protect. A private
 * copy of a shared list is FS-492's shape — and here the copy is of the one thing that has a
 * guard, so the guard covers a twelfth of what it appears to.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { extname, join, resolve } from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const SRC = resolve(__dirname, '..')

/** Non-null assertions. **Only ever goes down.** Measured 2026-08-08. */
const MAX_NON_NULL_ASSERTIONS = 30

/** Inline `.toLocale*()` calls that bypass `utils/formatters`. **Only down.** */
const MAX_INLINE_TO_LOCALE = 93

/** Calls to a `utils/formatters` helper. **Only ever goes UP.** */
const MIN_FORMATTER_CALLS = 65

/** Files carrying their own status→colour mapping. **Only down.** */
const MAX_COLOUR_MAP_FILES = 12

function sourceFiles(): string[] {
  const found: string[] = []
  const walk = (directory: string) => {
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry)
      if (statSync(path).isDirectory()) walk(path)
      else if (/\.tsx?$/.test(entry) && !/\.(test|spec)\./.test(entry)) found.push(path)
    }
  }
  walk(SRC)
  return found
}

function counts() {
  let nonNull = 0
  let inlineToLocale = 0
  let formatterCalls = 0
  const colourMapFiles = new Set<string>()

  for (const file of sourceFiles()) {
    const source = readFileSync(file, 'utf8')
    inlineToLocale += (source.match(/\.toLocale[A-Za-z]*\(/g) ?? []).length
    if (!file.includes('utils/formatters')) {
      formatterCalls += (
        source.match(/\bformat(?:Date|DateTime|TimeAgo|Duration|Bytes|Number|Percentage)\(/g) ??
        []
      ).length
    }
    if (/STATUS_COLORS|getStatusColor|statusColor|severityColor/.test(source)) {
      colourMapFiles.add(file.replace(`${SRC}/`, ''))
    }
    // PARSED, not grepped. `!` appears in `!foo`, `!==`, `a!.b` and inside every string in
    // the tree; only the AST distinguishes the assertion from the operator.
    const parsed = ts.createSourceFile(
      file,
      source,
      ts.ScriptTarget.Latest,
      true,
      extname(file) === '.tsx' ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    )
    const visit = (node: ts.Node) => {
      if (ts.isNonNullExpression(node)) nonNull += 1
      ts.forEachChild(node, visit)
    }
    visit(parsed)
  }

  return { nonNull, inlineToLocale, formatterCalls, colourMapFiles }
}

describe('frontend safety surfaces only shrink', () => {
  it('measures a plausible tree', () => {
    // Vacuity in both directions: zero means the walk broke, and an implausibly large
    // number means the detector stopped distinguishing what it counts.
    const { nonNull, inlineToLocale } = counts()
    expect(nonNull).toBeGreaterThan(5)
    expect(inlineToLocale).toBeGreaterThan(20)
  })

  it('has no more non-null assertions than the baseline', () => {
    const { nonNull } = counts()
    expect(
      nonNull,
      `${nonNull} non-null assertions, up from ${MAX_NON_NULL_ASSERTIONS}. Each tells the ` +
        `compiler to stop checking. Most existing ones are correct — TypeScript cannot narrow ` +
        `through a .filter() callback — but GeofencingPanel's \`radius!\` was a live crash on ` +
        `a polygon zone, in the file whose own header records the identical crash on the ` +
        `sibling field blanking the entire app. Narrow the type or guard the value.`,
    ).toBeLessThanOrEqual(MAX_NON_NULL_ASSERTIONS)
  })

  it('has no more inline toLocale calls than the baseline', () => {
    const { inlineToLocale } = counts()
    expect(
      inlineToLocale,
      `${inlineToLocale} inline .toLocale* calls, up from ${MAX_INLINE_TO_LOCALE}. ` +
        `utils/formatters wraps these in a try/catch returning 'Invalid date'; a bare call ` +
        `renders the literal string "Invalid Date" to a user when a timestamp is null or ` +
        `malformed. Use the helper.`,
    ).toBeLessThanOrEqual(MAX_INLINE_TO_LOCALE)
  })

  it('has no fewer formatter calls than the baseline', () => {
    // The pair. A cap on inline calls alone is satisfied by DELETING a call site; only
    // moving both together means a conversion was migrated rather than removed.
    const { formatterCalls } = counts()
    expect(
      formatterCalls,
      `${formatterCalls} calls to a utils/formatters helper, down from ` +
        `${MIN_FORMATTER_CALLS}. A safe conversion was replaced with an unsafe one, or ` +
        `deleted — either way the inline cap above no longer means what it says.`,
    ).toBeGreaterThanOrEqual(MIN_FORMATTER_CALLS)
  })

  it('has no more files carrying their own status-colour map', () => {
    const { colourMapFiles } = counts()
    expect(
      [...colourMapFiles].sort(),
      `${colourMapFiles.size} files map a status to a colour, up from ` +
        `${MAX_COLOUR_MAP_FILES}. STATUS_COLORS in utils/constants.ts has a contrast test ` +
        `protecting its ` +
        `values and the copies do not — pages/Alarms.tsx reproduces STATUS_COLORS verbatim, ` +
        `including the exact strings that test exists to protect. Import the shared map.`,
    ).toHaveLength(MAX_COLOUR_MAP_FILES)
  })

  it('the baselines are not slack', () => {
    // A ratchet set well above the real figure allows growth while reading as a constraint.
    const { nonNull, inlineToLocale } = counts()
    expect(MAX_NON_NULL_ASSERTIONS - nonNull).toBeLessThanOrEqual(3)
    expect(MAX_INLINE_TO_LOCALE - inlineToLocale).toBeLessThanOrEqual(5)
  })
})
