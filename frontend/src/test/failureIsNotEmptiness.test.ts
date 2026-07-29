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
 * a literal "No …" empty state. Both halves are needed: the query is what can fail, and
 * the empty string is where the failure lands.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')

const QUERIES = /\buse(?:Infinite)?Query\b/
/** `isError`, `status === 'error'`, or an `error ?` ternary — any of them counts. */
const HANDLES_ERROR = /\bisError\b|status\s*===\s*['"]error['"]|\berror\s*\?/
/** A literal empty state: `>No trailers found<` or `"No history for this metric"`. */
const EMPTY_STATE = [/>\s*(No [A-Za-z][^<>{]{2,40}?)\s*</g, /["'](No [A-Za-z][^"']{2,40})["']/g]

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

export function fallsThroughToEmptiness(source: string): string[] {
  if (!QUERIES.test(source)) return []
  if (HANDLES_ERROR.test(source)) return []
  return emptyStatesIn(source)
}

const FILES = sourceFiles(SRC)
const OFFENDERS = FILES.map((file) => ({
  file: file.slice(SRC.length + 1),
  states: fallsThroughToEmptiness(readFileSync(file, 'utf8')),
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

  it('accepts the same component once it handles the failure', () => {
    const good = `
      const { data, isError } = useQuery({ queryKey: ['x'], queryFn: f })
      if (isError) return <Error />
      return data?.items?.length ? <List /> : <p>No trailers found</p>
    `
    expect(fallsThroughToEmptiness(good)).toEqual([])
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
