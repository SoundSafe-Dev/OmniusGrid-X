/**
 * Every file in `e2e/` is collected by Playwright, or excused with a reason (FS-489).
 *
 * The suite is 49 tests across 6 files, and `e2e/` holds 7. The seventh —
 * `compliance-assistant.visual.ts` — is a standalone screenshot harness run with `npx tsx`,
 * and its extension keeps it out of the run ON PURPOSE. Its own docstring says so.
 *
 * WHAT THIS GUARDS IS THE OTHER FILE. Playwright's default `testMatch` collects only files
 * whose name carries a `.spec` or `.test` infix, and this config sets no `testMatch` of its
 * own — so **a spec that loses that infix silently stops running**. There is no error, no warning, and the suite goes
 * green faster than it did the day before — which is the direction nobody investigates. A
 * rename during a refactor, or a new file written as `foo.e2e.ts` because that reads better,
 * costs the whole file.
 *
 * That is the same shape as FS-484, where a walk keyed on import paths reported "no untested
 * pages" while two of the largest had no test — a resolver quietly not matching, and its
 * silence read as success.
 *
 * The exemption carries its reason and is checked for existence, per Rule 110: an allowlist
 * that keeps excusing a file nobody has looked at stops describing the code and starts
 * covering for it.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

const E2E_DIR = resolve(__dirname, '..', '..', 'e2e')

/** Playwright's default, since `playwright.config.ts` overrides `testMatch` only on the
 *  setup project. Kept as one regex so it can be compared to the config below. */
const DEFAULT_TEST_MATCH = /\.(spec|test)\.[cm]?[jt]sx?$/

/** The setup project's own `testMatch`, which collects a file that is not a spec. */
const SETUP_MATCH = /auth\.setup\.ts$/

/** Files in `e2e/` that Playwright is not meant to run, and why. */
const NOT_A_SPEC: Record<string, string> = {
  'routes.ts':
    'the shared route list, imported by two specs. It lives outside them because Playwright ' +
    'refuses spec-to-spec imports — "test file X should not import test file Y" fails ' +
    'collection for the WHOLE suite, and the symptom is `Total: 0 tests in 0 files`.',
  'compliance-assistant.visual.ts':
    'a standalone screenshot harness driven with `npx tsx`, not a test — it launches its ' +
    'own chromium, writes to OUT_DIR and asserts nothing. Its extension is the mechanism ' +
    'that keeps it out of the suite, and its docstring says so.',
}

function e2eFiles(): string[] {
  return readdirSync(E2E_DIR).filter((f) => f.endsWith('.ts'))
}

const FILES = e2eFiles()
const UNCOLLECTED = FILES.filter(
  (f) => !DEFAULT_TEST_MATCH.test(f) && !SETUP_MATCH.test(f) && !(f in NOT_A_SPEC),
)

describe('the reader is not vacuous', () => {
  it('finds the e2e files', () => {
    // An empty directory listing has no uncollected members and would pass silently.
    expect(FILES.length).toBeGreaterThan(4)
  })

  it('recognises a file it knows is collected', () => {
    expect(FILES).toContain('data-reaches-the-screen.spec.ts')
    expect(DEFAULT_TEST_MATCH.test('data-reaches-the-screen.spec.ts')).toBe(true)
  })

  it('recognises the setup file, which is collected by its own project', () => {
    expect(SETUP_MATCH.test('auth.setup.ts')).toBe(true)
    expect(DEFAULT_TEST_MATCH.test('auth.setup.ts')).toBe(false)
  })
})

describe('the playwright config still relies on the default testMatch', () => {
  it('sets no testMatch on the chromium project', () => {
    // If a `testMatch` is added to the chromium project, the regex above stops describing
    // what runs and this whole file starts guarding a fiction.
    const config = readFileSync(resolve(E2E_DIR, '..', 'playwright.config.ts'), 'utf8')
    const chromium = config.slice(config.indexOf("name: 'chromium'"))
    expect(chromium.slice(0, chromium.indexOf('}'))).not.toContain('testMatch')
  })
})

describe('no e2e file has quietly stopped running', () => {
  it('has none uncollected', () => {
    expect(
      UNCOLLECTED.map(
        (f) =>
          `e2e/${f} matches neither Playwright's default testMatch nor the setup project, ` +
          `so it is in the suite directory and runs in no job — add .spec to the name, or ` +
          `list it in NOT_A_SPEC with the reason it is not one`,
      ),
    ).toEqual([])
  })

  it('excuses nothing that has been deleted', () => {
    // A stale exemption is how an allowlist stops describing the code it guards.
    const ghosts = Object.keys(NOT_A_SPEC).filter((f) => !FILES.includes(f))
    expect(ghosts).toEqual([])
  })
})
