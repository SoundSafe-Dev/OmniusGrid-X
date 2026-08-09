/**
 * Every api client with a `USE_MOCK` fork has a real-mode test (FS-488).
 *
 * `src/test/setup.ts` stubs `VITE_USE_MOCK='true'` before any module evaluates, and
 * `mockMode.ts` reads it into a module-level `const`. So the default for every test in this
 * repository is the mock branch, and a client's real branch — the code that ships — runs in
 * no test at all unless somebody wrote one with `loadInRealMode`.
 *
 * That gap produced, among others: four dashboard tiles blank in production and complete in
 * development (FS-398), a `PATCH` wired to a button and served by nothing (FS-238), a
 * truncation flag discarded on arrival (FS-485), and a live map that kept drawing the last
 * positions it received (FS-487).
 *
 * WHY THIS GUARD EXISTS RATHER THAN A NOTE. The remaining count was tracked by hand across
 * several sessions and was wrong twice in a row — "six" written beside a list of seven, while
 * the true figure was eight, because a client whose COMPONENT had been tested was crossed off
 * as done. A number nobody derives is a number that drifts, and this one was drifting in the
 * flattering direction.
 *
 * THE BAR IS DELIBERATELY LOW. This asks whether a real-mode file exists beside the client,
 * not whether it covers every fork. What a test asserts is a reviewer's job; whether anyone
 * ever ran the real branch is checkable, and that is what this checks.
 */
import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

const API_DIR = resolve(__dirname, '..', 'api')

/** Infrastructure rather than clients: they define the mock mode or the fixtures themselves,
 *  so there is no real branch to exercise. */
const NOT_A_CLIENT = new Set(['mockMode.ts', 'mockApi.ts'])

/** Comments stripped before the search.
 *
 *  The first version matched the raw text, so a client that merely MENTIONED `USE_MOCK` in
 *  prose was demanded to have a real-mode test. `exportDeliveries.ts` was the first —
 *  its docstring explains why it has no mock branch, and saying so was enough to be
 *  reported as having one. A detector that reads documentation as code will eventually
 *  report the file that documents the very thing it is looking for. */
const COMMENT = /\/\*[\s\S]*?\*\/|(?<![:'"`])\/\/[^\n]*/g

export function hasMockFork(source: string): boolean {
  return source.replace(COMMENT, ' ').includes('USE_MOCK')
}

function clientsWithMockForks(): string[] {
  return readdirSync(API_DIR)
    .filter((f) => f.endsWith('.ts') && !f.includes('.test.') && !NOT_A_CLIENT.has(f))
    .filter((f) => hasMockFork(readFileSync(join(API_DIR, f), 'utf8')))
}

const FORKED = clientsWithMockForks()
const UNCOVERED = FORKED.filter(
  (f) => !existsSync(join(API_DIR, f.replace(/\.ts$/, '.realmode.test.ts'))),
)

describe('the sweep is not vacuous', () => {
  it('finds a plausible number of forked clients', () => {
    // A broken read returns nothing, and nothing has no uncovered members.
    expect(FORKED.length).toBeGreaterThan(10)
  })

  it('ignores a client that only mentions USE_MOCK in a comment', () => {
    // The false positive that produced this check. A file explaining why it has NO mock
    // branch must not be counted as having one.
    expect(hasMockFork('// this client has no USE_MOCK fork\nexport const x = 1')).toBe(false)
    expect(hasMockFork('/** no USE_MOCK here */\nexport const x = 1')).toBe(false)
  })

  it('still sees a real fork', () => {
    expect(hasMockFork('if (USE_MOCK) { return fixture }')).toBe(true)
  })

  it('recognises a client it knows has a real-mode test', () => {
    expect(FORKED).toContain('erp.ts')
    expect(existsSync(join(API_DIR, 'erp.realmode.test.ts'))).toBe(true)
  })
})

describe('no client ships an untested real branch', () => {
  it('has none uncovered', () => {
    expect(
      UNCOVERED.map(
        (f) =>
          `src/api/${f} branches on USE_MOCK and has no ${f.replace(/\.ts$/, '.realmode.test.ts')} — ` +
          `every test in this repository takes its mock branch, so the code that ships is ` +
          `exercised by nothing`,
      ),
    ).toEqual([])
  })
})
