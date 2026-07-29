/**
 * A component that queries and shows an empty state must also show an error state.
 *
 * Without one, a rejected query falls through to the empty branch and the screen says
 * "No trailers found" or "No history for this metric". Those are claims about the WORLD
 * — an empty yard, a silent sensor — and an operator acts on them. The truth is that the
 * request failed, which is a claim about the SYSTEM. React Query makes this easy to get
 * wrong: `data` is simply `undefined` on error, so `data?.items ?? []` renders emptiness
 * with no error anywhere in sight.
 *
 * WHAT IT FOUND. Two, and both mattered:
 *
 *   `YardManagement` — a failed trailer query rendered "No trailers found". A yard
 *   manager reads that as an operational fact and dispatches on it.
 *
 *   `TelemetryHistoryChart` — a failed history query rendered "No history for this
 *   metric", which an engineer diagnosing a machine reads as "this sensor produced
 *   nothing", concluding something about the equipment from a failure of the request.
 *
 * HOW IT WAS FOUND. Not by this sweep. It came out of writing a page test whose first
 * version asserted only that a known row was absent — true in BOTH states, so it passed
 * against the defect while claiming to guard it. Asserting each branch by its own text
 * is what made the silence visible, and the sweep was written afterwards to find the
 * rest.
 *
 * SCOPE. A component is in scope when it calls `useQuery`/`useInfiniteQuery` AND renders
 * a literal empty state. Both halves are needed: the query is what can fail, and the
 * empty string is where the failure lands. The phrase list covers "No …" plus "not
 * found", "nothing to …", "no results", "is empty" and "none yet" — see the pattern
 * below for why it grew on day two.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')

/** A CALL SITE, not the import. `import { useQuery } from '@tanstack/react-query'`
 *  matched the bare word and inflated every file's query count by one. */
const QUERIES = /\buse(?:Infinite)?Query\s*[<(]/g
/**
 * PER EMPTY STATE, not per file and not per count — and both earlier versions were wrong
 * in ways that hid live defects.
 *
 * v1 asked whether the FILE mentions `isError`. `TransportationManagement` has seven
 * queries; three handled failure and the shipments query did not, so the file looked
 * safe while a failed load rendered "No shipments found" to a dispatcher, who reads that
 * as "nothing is in transit".
 *
 * v2 counted queries against handlers. That found the transportation defect and three
 * more, but it cannot settle a file like `AdminPages`, which holds five separate page
 * components: a health query with no empty state is not a defect, and the count has no
 * way to know that.
 *
 * v3 is the actual property. For each empty state, look at the conditional chain it sits
 * in and ask whether a failure branch precedes it. That is exactly what has to be true,
 * and it is local enough to be decided without guessing which query feeds which list.
 */
/**
 * Every form this codebase uses to branch on failure. Keying on the ternary alone
 * accused two correct pages: `AlarmRules` renders its failure with `{isError && …}` and
 * guards the empty state with `!isError`, and `AssetDetail` returns early with
 * `if (isError)`, and `Dashboard` hands `isError={q.isError}` to a widget that owns the
 * three states together. Four broadenings, each one found by the next false positive:
 * a detector that knows one idiom under-counts a codebase that uses five — the same
 * lesson the tenant-session guard learned about `AsyncSessionLocal`.
 */
const ERROR_BRANCH =
  /\b(?:isError|[A-Za-z]+Error)\s*(?:\?|&&|=)|!\s*(?:isError|[A-Za-z]+Error)\b|if\s*\(\s*(?:isError|[A-Za-z]+Error)\s*\)|status\s*===\s*['"]error['"]/
/**
 * Comments are stripped before any of this runs, for two reasons that turned out to be
 * the same reason. A comment EXPLAINING this defect quotes the empty-state text, so the
 * quoted-string pattern matched the prose and reported a second, phantom empty state.
 * And that same comment sat between the failure branch and the real JSX node, pushing
 * them more than a window apart, so the genuine one looked unguarded. Method rule 14,
 * for the third time in this repository: a match on raw source is satisfied — and
 * displaced — by prose.
 */
const COMMENT = /\/\*[\s\S]*?\*\/|(?<![:'"`])\/\/[^\n]*/g
/**
 * An early return guards EVERYTHING after it, however far away.
 *
 * `OEE` and `ErrorTriageDetail` both do `if (isError) return <Err/>` near the top of the
 * component and render their empty states hundreds of lines below. A proximity window
 * cannot see that, and reported three correct empty states as unguarded. Distance is the
 * wrong question for this idiom: the guard is unconditional from that point on.
 */
const EARLY_RETURN =
  /if\s*\([^)]*\b(?:isError|[A-Za-z]+Error)\b[^)]*\)\s*\{?\s*(?:return|\n\s*return)/

/** How far back to look for a failure branch in the same conditional chain. Used only
 *  for the inline forms — a ternary, an `&&`, or an `isError=` prop — which really are
 *  local to the JSX they guard.
 *
 *  2500, not 900. Every genuine offender had its empty branch immediately after the
 *  loading one, a few dozen characters away. What sits between a REAL failure branch and
 *  the empty state is that branch's own markup — an alert div, an icon, a retry button,
 *  a second line of explanation — which on two pages ran to 919 and 1323 characters and
 *  pushed correct code outside the window. Erring small produces false positives on
 *  exactly the pages that took the trouble to explain themselves, which is the worst
 *  possible incentive. */
const CHAIN_WINDOW = 2500
/** A literal empty state.
 *
 * KEYED ON MORE THAN "No …", because that was the guard's entry point on day one and
 * `AssetDetail` says "Asset not found" — a phrasing the original pattern could not see,
 * and a sharper claim than most: it asserts the thing does not EXIST. That page already
 * handles failure (its comment records the same defect being fixed there earlier), so
 * nothing was hiding in the gap. The pattern is widened anyway, because a blind spot
 * that happens to be empty today is still a blind spot — method rule 18.
 */
const EMPTY_PHRASE =
  String.raw`(?:No [A-Za-z][^<>{"']{2,40}|[A-Za-z][^<>{"']{0,30}(?:not found|nothing to [a-z]+|no results|is empty|none yet)[^<>{"']{0,20})`
const EMPTY_STATE = [
  new RegExp(String.raw`>\s*(${EMPTY_PHRASE})\s*<`, 'g'),
  new RegExp(String.raw`["'](${EMPTY_PHRASE})["']`, 'g'),
]

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return sourceFiles(full)
    if (!entry.endsWith('.tsx') || entry.includes('.test.')) return []
    return [full]
  })
}

export function emptyStatesIn(source: string): string[] {
  const found: string[] = []
  for (const pattern of EMPTY_STATE) {
    for (const match of source.matchAll(pattern)) found.push(match[1].trim())
  }
  return [...new Set(found)]
}

export function fallsThroughToEmptiness(raw: string, _file = ''): string[] {
  const source = raw.replace(COMMENT, ' ')
  if (!(source.match(QUERIES) ?? []).length) return []
  const unguarded: string[] = []
  for (const pattern of EMPTY_STATE) {
    for (const match of source.matchAll(pattern)) {
      const before = source.slice(0, match.index!)
      if (EARLY_RETURN.test(before)) continue
      const chain = before.slice(Math.max(0, before.length - CHAIN_WINDOW))
      if (!ERROR_BRANCH.test(chain)) unguarded.push(match[1].trim())
    }
  }
  return [...new Set(unguarded)]
}

const FILES = sourceFiles(SRC)
const OFFENDERS = FILES.map((file) => ({
  file: file.slice(SRC.length + 1),
  states: fallsThroughToEmptiness(readFileSync(file, 'utf8'), file.slice(SRC.length + 1)),
})).filter((o) => o.states.length > 0)

const QUERYING = FILES.filter((f) => QUERIES.test(readFileSync(f, 'utf8')))

describe('the sweep is not vacuous', () => {
  it('reaches the components', () => {
    expect(FILES.length).toBeGreaterThan(50)
  })

  it('finds the ones that query', () => {
    // If the query pattern stops matching, every file looks safe and this file passes
    // while inspecting nothing.
    expect(QUERYING.length).toBeGreaterThan(15)
  })

  it('flags a component that queries, shows emptiness and ignores failure', () => {
    const bad = `
      const { data } = useQuery({ queryKey: ['x'], queryFn: f })
      return data?.items?.length ? <List /> : <p>No trailers found</p>
    `
    expect(fallsThroughToEmptiness(bad)).toEqual(['No trailers found'])
  })

  it('accepts an early return however far it sits from the empty state', () => {
    const padding = 'y'.repeat(CHAIN_WINDOW + 100)
    const guarded = `
      const { data, isError } = useQuery({ queryKey: ['x'], queryFn: f })
      if (isError) return <Err />
      ${padding}
      return data?.length ? <List /> : <p>No OEE data available</p>
    `
    expect(fallsThroughToEmptiness(guarded)).toEqual([])
  })

  it('accepts the same component once it handles the failure', () => {
    const good = `
      const { data, isError } = useQuery({ queryKey: ['x'], queryFn: f })
      return isError ? <Err /> : data?.items?.length ? <List /> : <p>No trailers found</p>
    `
    expect(fallsThroughToEmptiness(good)).toEqual([])
  })

  it('flags a file whose OTHER queries handle failure while one does not', () => {
    // The correction that found the transportation defect. Asking whether the file
    // mentions `isError` passes any page where a single query happens to handle it.
    // The other query's handler is in the file but not in this chain and not an early
    // return, so the shipments list still falls through. The padding stands in for the
    // hundreds of lines that separate them in the real page — proximity is the only
    // signal available for the inline forms, and this is where its limit sits.
    const padding = 'x'.repeat(CHAIN_WINDOW + 100)
    const partial = `
      const a = useQuery({ queryKey: ['a'], queryFn: f })
      const { isError } = useQuery({ queryKey: ['b'], queryFn: g })
      const other = isError ? <Err /> : null
      ${padding}
      return a.data?.length ? <List /> : <p>No shipments found</p>
    `
    expect(fallsThroughToEmptiness(partial)).toContain('No shipments found')
  })

  it('sees an empty state that does not start with "No"', () => {
    // `Asset not found` is the sharper claim — it says the thing does not EXIST — and
    // the day-one pattern could not match it.
    const bad = `
      const { data } = useQuery({ queryKey: ['a'], queryFn: f })
      return data ? <Detail /> : <p>Asset not found</p>
    `
    expect(fallsThroughToEmptiness(bad)).toContain('Asset not found')
  })

  it('ignores a component with an empty state but no query', () => {
    // A presentational list given its rows as props cannot fail a request, so it has
    // nothing to distinguish. Flagging it would be noise.
    expect(fallsThroughToEmptiness('return <p>No items selected</p>')).toEqual([])
  })
})

describe('no querying component renders a failure as emptiness', () => {
  it('has no offenders', () => {
    expect(
      OFFENDERS.map(
        (o) =>
          `${o.file} — a failed query falls through to ${JSON.stringify(o.states)}, ` +
          `which reads as a fact about the world rather than about the request`,
      ),
    ).toEqual([])
  })
})
