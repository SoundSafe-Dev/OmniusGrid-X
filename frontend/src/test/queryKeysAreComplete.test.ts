/**
 * A `useQuery` key must name everything its `queryFn` varies on.
 *
 * React Query caches on the key alone. If the fetch depends on a value the key does not
 * mention, changing that value serves the PREVIOUS result straight from cache — no
 * refetch, no loading state, no error. The screen updates its controls and not its data,
 * which reads as "the filter doesn't work" and is nearly impossible to catch by clicking
 * around, because the first render is always right.
 *
 * WHY THIS EXISTS. Fixing `/api/v1/auth/users` to paginate meant `AdminPages` had to send
 * an explicit page size, and the first version of that change kept the original
 * `queryKey: ['users']` while the fetch became `getUsers({ limit })`. Pressing "Show more"
 * would have re-read the same 50 rows forever. It was caught before commit; nothing in
 * the type system or the test suite would have caught it after.
 *
 * The codebase is clean at 0 offenders, and the value here is entirely in staying that
 * way — this is a mistake that costs one line to make.
 *
 * THE DETECTOR WAS WRONG FIRST, in the way these sweeps usually are. It read identifiers
 * out of the call arguments and flagged seven sites, ALL correct:
 *
 *   - six passed an object literal like `{ limit: 500 }`, where `limit` is a KEY with a
 *     constant value and varies with nothing. Object keys are stripped before matching —
 *     the same correction the backend's query-parameter sweep needed;
 *   - one passed `startTime`, derived one line above from `timeRange`, which IS in the
 *     key. A derived value is covered transitively, so a dependency whose declaration
 *     mentions a key variable is not reported.
 *
 * Both corrections are pinned below, because a detector that reports correct code gets
 * ignored, and the next real finding is ignored with it.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')

/** Identifiers that appear in call arguments but never represent a cache dependency. */
const NOT_A_DEPENDENCY = new Set([
  'true', 'false', 'null', 'undefined', 'async', 'await', 'return', 'new',
  'Date', 'String', 'Number', 'Boolean', 'JSON', 'Math', 'Object', 'Array',
  'console', 'window', 'document',
])

const IDENTIFIER = /[A-Za-z_$][\w$]*/g
/** `name:` — an object key, not a value. */
const OBJECT_KEY = /[A-Za-z_$][\w$]*\s*:/g

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return sourceFiles(full)
    if (!/\.tsx?$/.test(entry) || entry.includes('.test.')) return []
    return [full]
  })
}

/** The balanced bracket span starting at `open`. */
function balanced(text: string, open: number): string {
  let depth = 0
  for (let i = open; i < text.length; i++) {
    if ('([{'.includes(text[i])) depth++
    else if (')]}'.includes(text[i])) {
      depth--
      if (depth === 0) return text.slice(open, i + 1)
    }
  }
  return ''
}

function identifiers(text: string): Set<string> {
  return new Set(text.match(IDENTIFIER) ?? [])
}

export interface Incomplete {
  file: string
  line: number
  key: string
  missing: string[]
}

export function findIncompleteKeys(source: string, file = 'inline'): Incomplete[] {
  const found: Incomplete[] = []
  const useQuery = /useQuery\s*(?:<[^>]*>)?\s*\(\s*\{/g
  let match: RegExpExecArray | null

  while ((match = useQuery.exec(source)) !== null) {
    const body = balanced(source, match.index + match[0].length - 1)
    const keyAt = body.match(/queryKey\s*:\s*\[/)
    const fnAt = body.match(/queryFn\s*:/)
    if (!keyAt || !fnAt || keyAt.index === undefined || fnAt.index === undefined) continue

    const key = balanced(body, keyAt.index + keyAt[0].length - 1)
    const call = body.slice(fnAt.index).slice(0, 400).match(/\w+\s*\(([^()]*)\)/)
    if (!call) continue

    // Strip object keys: `{ limit: 500 }` varies with nothing.
    const args = call[1].replace(OBJECT_KEY, '')
    const keyNames = identifiers(key)
    const missing = [...identifiers(args)].filter((name) => {
      if (NOT_A_DEPENDENCY.has(name) || /^[A-Z]/.test(name)) return false
      if (keyNames.has(name)) return false
      // Derived from something already in the key — covered transitively.
      const declaration = source.match(
        new RegExp(`(?:const|let|var)\\s+${name}\\s*=([^;\\n]*)`),
      )
      if (declaration && [...identifiers(declaration[1])].some((n) => keyNames.has(n))) {
        return false
      }
      return true
    })

    if (missing.length) {
      found.push({
        file,
        line: source.slice(0, match.index).split('\n').length,
        key: key.replace(/\s+/g, ' '),
        missing: missing.sort(),
      })
    }
  }
  return found
}

const FILES = sourceFiles(SRC)
const OFFENDERS = FILES.flatMap((file) =>
  findIncompleteKeys(readFileSync(file, 'utf8'), file.slice(SRC.length + 1)),
)
const TOTAL_QUERIES = FILES.reduce(
  (n, file) => n + (readFileSync(file, 'utf8').match(/useQuery\s*[<(]/g)?.length ?? 0),
  0,
)

describe('the sweep is not vacuous', () => {
  it('reaches the pages', () => {
    expect(FILES.length).toBeGreaterThan(50)
  })

  it('finds the useQuery calls it is meant to check', () => {
    // A rename or a wrapper hook would otherwise make this pass while checking nothing.
    expect(TOTAL_QUERIES).toBeGreaterThan(30)
  })

  it('flags a key that omits a real dependency', () => {
    // The exact shape that nearly shipped in AdminPages.
    const bad = `useQuery({ queryKey: ['users'], queryFn: () => authApi.getUsers({ limit }) })`
    expect(findIncompleteKeys(bad)[0]?.missing).toEqual(['limit'])
  })

  it('accepts the same call once the key names the dependency', () => {
    const good = `useQuery({ queryKey: ['users', limit], queryFn: () => authApi.getUsers({ limit }) })`
    expect(findIncompleteKeys(good)).toEqual([])
  })
})

describe('the detector does not report correct code', () => {
  it('treats an object key as a key, not a variable', () => {
    // Six real sites look like this. `limit` is a field name with a constant value.
    const fine = `useQuery({ queryKey: ['assets'], queryFn: () => assetsApi.list({ limit: 500 }) })`
    expect(findIncompleteKeys(fine)).toEqual([])
  })

  it('accepts a value derived from something already in the key', () => {
    // `startTime` recomputes whenever `timeRange` changes, and `timeRange` is in the
    // key — so the cache already turns over. Reporting it would be a false positive.
    const derived = `
      const startTime = new Date(Date.now() - RANGE[timeRange] * 3600000).toISOString()
      useQuery({
        queryKey: ['telemetry', asset?.id, timeRange],
        queryFn: () => telemetryApi.getHistory(asset!.id, { startTime }),
      })`
    expect(findIncompleteKeys(derived)).toEqual([])
  })

  it('ignores constants and globals', () => {
    const fine = `useQuery({ queryKey: ['x'], queryFn: () => api.get(HOURS, Date.now()) })`
    expect(findIncompleteKeys(fine)).toEqual([])
  })
})

describe('every query key names what its fetch depends on', () => {
  it('has no cache keys missing a dependency', () => {
    expect(
      OFFENDERS.map(
        (o) =>
          `${o.file}:${o.line} key ${o.key} omits ${o.missing.join(', ')} — changing ` +
          `it serves the previous result from cache with no refetch`,
      ),
    ).toEqual([])
  })
})
