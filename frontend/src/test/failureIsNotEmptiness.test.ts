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
 * A SECOND DETECTOR LIVES AT THE BOTTOM OF THIS FILE, for the form the first one is
 * structurally blind to. `FleetOverview` gated its live vehicle map on a value derived
 * from an unguarded query — `{orgId && <GeoTabIntegration …>}` where `orgId` came from
 * `orgs?.[0]?.id`. On failure the widget was simply not rendered. There is no empty
 * state to match because there is no string: the page draws its other tiles and looks
 * finished while the thing it exists for is gone. Absence of a sentence and absence of a
 * component are the same defect; only one of them is greppable by phrase.
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
 *
 * WIDENED A THIRD TIME, and this time something WAS hiding in the gap. The cap was 40
 * characters, and `StrategicEngine` says
 *
 *     No pending recommendations. Check back later for new suggestions from the cloud
 *     strategic engine.
 *
 * — about a hundred. The guard reported zero offenders across the tree while that sat
 * unguarded, which is the exact failure mode rule 21 is about: a clean sweep is a claim
 * about the SWEEP until something proves it can still fail. A helpful empty state is
 * longer than a terse one, so the cap was hardest on the pages that explained themselves
 * best. 120 now, still bounded so it cannot run across a whole JSX subtree.
 */
const EMPTY_PHRASE =
  String.raw`(?:No [A-Za-z][^<>{"']{2,120}|[A-Za-z][^<>{"']{0,30}(?:not found|nothing to [a-z]+|no results|is empty|none yet)[^<>{"']{0,20})`
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

/** A `{isError && (…)}` block that CLOSES before the empty state guards nothing.
 *
 * This is how `StrategicEngine` escaped. Its failure banner sits at the top of the page
 * and the empty state is a hundred lines below, but the banner was inside the proximity
 * window, so the chain "contained an error branch" and the file looked clean. A banner
 * marks a failure; it does not stand in the way of anything after it — rule 24, arriving
 * in the guard itself.
 *
 * Brace counting, not a regex: a JSX expression container ends at its matching `}`, and
 * nesting is exactly what a pattern cannot follow. If the container holding this
 * `isError` closes before `emptyAt`, the occurrence is a banner and does not count.
 *
 * NARROW ON PURPOSE — it applies only to a whole JSX container that OPENS with an error
 * check, `{someError && …}` or `{someError ? … : …}`.
 *
 * The `?` form is not optional, and leaving it out is what still hid `StrategicEngine`
 * after the length cap was widened. Its nearest error branch was
 * `{optimizeMutation.isError ? (…)}` — a DIFFERENT mutation, in a different card, 1669
 * characters away and therefore inside the window. Proximity had found an error branch
 * that guards a completely unrelated thing. When the container opens with a ternary and
 * the empty state is inside it, brace counting still says "guards"; when it closed two
 * cards earlier, it now correctly says it does not. The first version counted braces from whatever `{` came
 * before the match, and defaulting to "does not guard" made it wrong twice at once: it
 * anchored on the `{ data, isError }` of the destructuring, and on `isError={q.isError}`
 * passed as a PROP, where the guard is the receiving component and position is
 * irrelevant. Both are real guards and both got flagged. Everything that is not the
 * banner idiom is now assumed to guard, so the check can only ever remove a false
 * negative, never manufacture a false positive.
 */
const BANNER_BLOCK = /^\s*(?:[A-Za-z.]*\b(?:isError|[A-Za-z]+Error))\s*(?:&&|\?)/

function guardsPosition(source: string, errorAt: number, emptyAt: number): boolean {
  const open = source.lastIndexOf('{', errorAt)
  if (open === -1) return true
  if (!BANNER_BLOCK.test(source.slice(open + 1, errorAt + 40))) return true
  let depth = 0
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') {
      depth--
      if (depth === 0) return i > emptyAt
    }
  }
  return true
}

/** Empty states whose condition is a field on an ALREADY-RENDERED item, not on a query
 *  result. Each entry is a claim that the phrase cannot be reached by a failed request;
 *  `TestTheExemptionsStayHonest` re-proves the phrase still exists so the list cannot
 *  quietly describe code that has moved on. */
export const NOT_A_QUERY_EMPTY_STATE: Record<string, string> = {
  // `a.notificationDispatched ? … : …` inside the assessment list — `a` is one rendered
  // assessment, so this line exists only when the query already returned data. It
  // describes THAT assessment, not the absence of a response.
  'No notification dispatched for this assessment':
    'pages/predictive/PredictiveMaintenance.tsx',
}

export function fallsThroughToEmptiness(raw: string, _file = ''): string[] {
  const source = raw.replace(COMMENT, ' ')
  if (!(source.match(QUERIES) ?? []).length) return []
  const unguarded: string[] = []
  for (const pattern of EMPTY_STATE) {
    for (const match of source.matchAll(pattern)) {
      const phrase = match[1].trim()
      if (phrase in NOT_A_QUERY_EMPTY_STATE) continue
      const before = source.slice(0, match.index!)
      if (EARLY_RETURN.test(before)) continue
      const chain = before.slice(Math.max(0, before.length - CHAIN_WINDOW))
      const chainStart = before.length - chain.length
      const guarded = [...chain.matchAll(new RegExp(ERROR_BRANCH.source, 'g'))].some((e) =>
        guardsPosition(source, chainStart + e.index!, match.index!),
      )
      if (!guarded) unguarded.push(phrase)
    }
  }
  return [...new Set(unguarded)]
}

const FILES = sourceFiles(SRC)
const OFFENDERS = FILES.map((file) => ({
  file: file.slice(SRC.length + 1),
  states: fallsThroughToEmptiness(readFileSync(file, 'utf8'), file.slice(SRC.length + 1)),
})).filter((o) => o.states.length > 0)

/** `.match()`, NOT `QUERIES.test()`.
 *
 * `QUERIES` carries the `g` flag, and `RegExp.prototype.test` on a global regex is
 * STATEFUL — it advances `lastIndex` and resumes from there on the next call, so
 * consecutive `.test()` calls over different strings alternate between finding and not
 * finding the same pattern. This filter therefore returned a different count depending on
 * how many files preceded each one and how long they were.
 *
 * It had been passing by luck. Editing four unrelated pages moved enough characters to
 * drop the count under the threshold, and the vacuity check failed with nothing wrong in
 * the code it guards. A guard whose own result depends on iteration order cannot tell you
 * anything about the tree — this is the third regex bug in this file, and the first that
 * made the sweep's own honesty check unreliable. */
const QUERYING = FILES.filter((f) => (readFileSync(f, 'utf8').match(QUERIES) ?? []).length > 0)

describe('the sweep is not vacuous', () => {
  it('reaches the components', () => {
    expect(FILES.length).toBeGreaterThan(50)
  })

  it('counts the querying files the same way twice', () => {
    // The regression that made this suite fail with nothing wrong in the tree. `QUERIES`
    // is global, and `.test()` on a global regex advances `lastIndex`, so the old filter
    // alternated between matching and not matching identical content. Asserting the count
    // is stable across two passes is what makes the threshold below mean anything.
    const countOnce = () =>
      FILES.filter((f) => (readFileSync(f, 'utf8').match(QUERIES) ?? []).length > 0).length
    expect(countOnce()).toBe(countOnce())
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

  it('does not accept a banner that closes before the empty state', () => {
    // HOW STRATEGICENGINE ESCAPED. A `{isError && (…)}` block at the top of the page
    // marks the failure and stands in the way of nothing after it, but it sat inside the
    // proximity window, so the chain "contained an error branch" and the file read clean.
    const banner = `
      const { data, isError } = useQuery({ queryKey: ['x'], queryFn: f })
      return (
        <div>
          {isError && (<Card><p>Failed to load recommendations.</p></Card>)}
          <Card>
            {(data ?? []).length === 0 ? (
              <p>No pending recommendations. Check back later for new suggestions.</p>
            ) : <List />}
          </Card>
        </div>
      )
    `
    expect(fallsThroughToEmptiness(banner)).toContain(
      'No pending recommendations. Check back later for new suggestions.',
    )
  })

  it('still accepts a banner that WRAPS the empty state', () => {
    // The same idiom used correctly: the container has not closed, so it really is the
    // alternative branch. Without this the rule above would flag it.
    const wrapping = `
      const { data, isError } = useQuery({ queryKey: ['x'], queryFn: f })
      return <div>{isError ? <Err /> : <p>No pending recommendations here at all.</p>}</div>
    `
    expect(fallsThroughToEmptiness(wrapping)).toEqual([])
  })

  it('still accepts isError passed as a prop to the component that renders both', () => {
    // The Dashboard idiom. The guard is the receiving component, so position says
    // nothing — the first version of the banner rule flagged all six of its widgets.
    const viaProp = `
      const q = useQuery({ queryKey: ['x'], queryFn: f })
      return <Widget isError={q.isError} isEmpty={!q.data?.count} emptyLabel="No active alarms" />
    `
    expect(fallsThroughToEmptiness(viaProp)).toEqual([])
  })

  it('sees an empty state longer than the old forty-character cap', () => {
    // The cap is why StrategicEngine's phrase was invisible even before the banner
    // question arose. A helpful empty state is longer than a terse one, so the limit bit
    // hardest on the pages that explained themselves best.
    const verbose = `
      const { data } = useQuery({ queryKey: ['x'], queryFn: f })
      return <p>No pending recommendations. Check back later for new suggestions from the cloud engine.</p>
    `
    expect(fallsThroughToEmptiness(verbose).length).toBe(1)
  })

  it('ignores a component with an empty state but no query', () => {
    // A presentational list given its rows as props cannot fail a request, so it has
    // nothing to distinguish. Flagging it would be noise.
    expect(fallsThroughToEmptiness('return <p>No items selected</p>')).toEqual([])
  })
})

describe('the per-item exemptions stay honest', () => {
  // An exemption is a claim: "a failed request cannot reach this phrase, because the
  // condition is a field on an item the query already returned". Claims rot. These make
  // each one re-prove itself, so the list cannot become somewhere findings go to be
  // forgotten — the same discipline as the backend's QUALIFIES_AN_UNREAD_FIELD.
  it('names a file that still contains the phrase', () => {
    const missing = Object.entries(NOT_A_QUERY_EMPTY_STATE).filter(
      ([phrase, file]) => !readFileSync(join(SRC, file), 'utf8').includes(phrase),
    )
    expect(missing).toEqual([])
  })

  it('stays short enough to read', () => {
    // Not a limit for its own sake: a list nobody reads is a list nobody audits, and
    // this one exists to hold false positives, not findings.
    expect(Object.keys(NOT_A_QUERY_EMPTY_STATE).length).toBeLessThanOrEqual(5)
  })

  it('would flag the exempted phrase without the exemption', () => {
    // If the pattern stopped matching these phrases entirely, the entries would be dead
    // weight AND the sweep would have quietly narrowed. This proves they are still live.
    const [phrase] = Object.keys(NOT_A_QUERY_EMPTY_STATE)
    const source = `
      const { data } = useQuery({ queryKey: ['x'], queryFn: f })
      return <p>${phrase}</p>
    `
    expect(emptyStatesIn(source)).toContain(phrase)
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

// ---------------------------------------------------------------------------
// A WIDGET GATED ON AN UNGUARDED QUERY.
//
// `{orgId && <GeoTabIntegration …>}`, where `orgId` traces back to a `useQuery`
// destructured without `isError`. A rejected query makes the gate falsy and the widget
// disappears — no empty state, no error, no gap. The phrase-based sweep above cannot see
// this, because the failure renders as nothing at all rather than as a sentence.
//
// Two hops of derivation are followed (`data` -> `orgs?.[0]?.id` -> the gate), which is
// what the real defect needed. Deeper chains are not tracked; the guard is a floor.
// ---------------------------------------------------------------------------

const DESTRUCTURED_QUERY = /const\s*\{([^}]*)\}\s*=\s*useQuery/g
const HANDLES_FAILURE = /\b(isError|error|isSuccess|status)\b/
const GATED_WIDGET = /\{\s*([\w.?]+)\s*(?:&&|\?)\s*[(\s]*<([A-Z]\w+)/g

export function widgetsGatedOnUnguardedQueries(raw: string): string[] {
  const source = raw.replace(COMMENT, ' ')
  if (!(source.match(QUERIES) ?? []).length) return []

  const unguarded = new Set<string>()
  for (const match of source.matchAll(DESTRUCTURED_QUERY)) {
    if (HANDLES_FAILURE.test(match[1])) continue
    for (const part of match[1].split(',')) {
      // `data: orgs` binds `orgs`; a bare `data` binds `data`.
      const name = part.split(':').pop()!.trim()
      if (name) unguarded.add(name)
    }
  }
  if (!unguarded.size) return []

  const tainted = new Set(unguarded)
  for (let hop = 0; hop < 2; hop++) {
    for (const name of [...tainted]) {
      const assigned = new RegExp(String.raw`const\s+(\w+)\s*=\s*[^;\n]*\b${name}\b`, 'g')
      for (const match of source.matchAll(assigned)) tainted.add(match[1])
    }
  }

  const found: string[] = []
  for (const match of source.matchAll(GATED_WIDGET)) {
    const root = match[1].split('?')[0].split('.')[0]
    if (tainted.has(root)) found.push(`{${match[1]} && <${match[2]}>}`)
  }
  return [...new Set(found)]
}

const GATED = FILES.map((file) => ({
  file: file.slice(SRC.length + 1),
  gates: widgetsGatedOnUnguardedQueries(readFileSync(file, 'utf8')),
})).filter((g) => g.gates.length > 0)

describe('the widget-gate sweep is not vacuous', () => {
  it('flags a widget gated on a query that ignores failure', () => {
    // The defect verbatim, as FleetOverview carried it.
    const bad = `
      const { data: orgs } = useQuery({ queryKey: ['fleet-orgs'], queryFn: f })
      const orgId = orgs?.[0]?.id
      return <div>{orgId && <GeoTabIntegration organizationId={orgId} />}</div>
    `
    expect(widgetsGatedOnUnguardedQueries(bad)).toEqual(['{orgId && <GeoTabIntegration>}'])
  })

  it('accepts the same widget once the query handles failure', () => {
    const good = `
      const { data: orgs, isError: orgsError } = useQuery({ queryKey: ['o'], queryFn: f })
      const orgId = orgs?.[0]?.id
      return <div>{orgId ? <GeoTabIntegration organizationId={orgId} /> : <Notice />}</div>
    `
    expect(widgetsGatedOnUnguardedQueries(good)).toEqual([])
  })

  it('ignores a gate whose value never came from a query', () => {
    // A widget behind a local toggle or a prop cannot vanish because a request failed.
    const fine = `
      const { data, isError } = useQuery({ queryKey: ['x'], queryFn: f })
      const [open, setOpen] = useState(false)
      return <div>{open && <Drawer />}</div>
    `
    expect(widgetsGatedOnUnguardedQueries(fine)).toEqual([])
  })

  it('ignores a component that does not query', () => {
    expect(widgetsGatedOnUnguardedQueries('return <div>{x && <Panel />}</div>')).toEqual([])
  })
})

describe('no widget disappears because a query failed', () => {
  it('has no offenders', () => {
    expect(
      GATED.map(
        (g) =>
          `${g.file} — ${g.gates.join(', ')} is gated on a query that does not handle ` +
          `failure, so a rejected request removes the widget with nothing in its place`,
      ),
    ).toEqual([])
  })
})
