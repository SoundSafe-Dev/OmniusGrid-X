import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

/**
 * A large `limit` in a query call must be a named constant, not a bare number (FS-900).
 *
 * `DEFAULT_PAGE_SIZE` (20) and `MAX_PAGE_SIZE` (100) were declared in constants.ts with
 * zero consumers anywhere in the tree — every large fetch used its own bare number
 * instead, four of them the identical `limit: 500` with no shared name and no link to
 * what actually bounds it (assetsApi's own `GET /api/v1/assets` ceiling). A bare number
 * repeated four times is four places to update, silently, if the backend ceiling ever
 * moves — and nothing here says WHY 500 rather than some other value.
 *
 * WHY THIS DOES NOT ENFORCE MAX_PAGE_SIZE ITSELF. The four sites this found are
 * fleet-overview fetches — "give me the whole fleet for a KPI tile", not a paginated
 * table — and MAX_PAGE_SIZE (100) is too small for that job on any fleet bigger than
 * 100 assets; clamping to it would make FS-967's truncation bug worse, not fix it.
 * `FLEET_OVERVIEW_FETCH_LIMIT` names that different question explicitly instead.
 */

const PAGES = join(__dirname, '..', 'pages')

//: Bare numeric limits this large are almost always meant to say "everything", which is
//: exactly the claim that needs a name and a reason, not a literal.
const BARE_LARGE_LIMIT = /\blimit:\s*(\d+)/g
const THRESHOLD = 200

//: Call sites checked and left as a bare number, each with why. An entry here is a
//: decision on the record, not a silence — see rule 295's shape, avoided by naming
//: the reason rather than raising a threshold to make the finding disappear.
const ACCEPTED_BARE: Record<string, string> = {
  'Alarms.tsx': 'limit: 200 populates a <select>, not a table; FS-961 registers a proper typeahead endpoint as the real fix.',
  'AlarmRules.tsx': 'Same as Alarms.tsx — asset picker, not a list view.',
  'ShopFloor.tsx': 'Same as Alarms.tsx — asset picker, not a list view.',
  'Historian.tsx': 'limit: 5000 matches historian.py\'s own `le=5000` ceiling on GET /historian/query exactly — a single-metric time-series pull, not a paginated table MAX_PAGE_SIZE was meant for.',
}

function* walk(dir: string): Generator<string> {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    const stat = statSync(full)
    if (stat.isDirectory()) yield* walk(full)
    else if (entry.endsWith('.tsx') && !entry.includes('.test.')) yield full
  }
}

function offenders(): string[] {
  const found: string[] = []
  for (const file of walk(PAGES)) {
    const base = file.split('/').pop()!
    if (base in ACCEPTED_BARE) continue
    const source = readFileSync(file, 'utf-8')
    for (const match of source.matchAll(BARE_LARGE_LIMIT)) {
      if (Number(match[1]) >= THRESHOLD) {
        found.push(`${base}: limit: ${match[1]}`)
      }
    }
  }
  return found
}

describe('a large limit is a named constant, not a bare number', () => {
  it('the sweep can see its subject', () => {
    // A guard that finds nothing passes for the wrong reason. If FLEET_OVERVIEW_FETCH_LIMIT
    // or the accepted-select fetches are ever removed outright, this should drop to zero
    // legitimately — verified instead by confirming the accepted register still names
    // real files, so a renamed/removed page surfaces here rather than silently exempting
    // whatever replaced it.
    const files = new Set([...walk(PAGES)].map((f) => f.split('/').pop()))
    for (const name of Object.keys(ACCEPTED_BARE)) {
      expect(files.has(name), `${name} no longer exists; update ACCEPTED_BARE`).toBe(true)
    }
  })

  it('no page hardcodes a bare large limit outside the accepted register', () => {
    const found = offenders()
    expect(
      found,
      `these limits should reference a named constant (FLEET_OVERVIEW_FETCH_LIMIT, or ` +
        `a backend-ceiling-matching value with a comment saying so) instead of a bare ` +
        `number:\n  ${found.join('\n  ')}`,
    ).toEqual([])
  })
})
