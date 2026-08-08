/**
 * Every `vi.mock` path resolves to a real module (FS-544 / FS-581).
 *
 * THE DEFECT. `Kanban.test.tsx` carried two mocks that pointed at nothing:
 *
 *     vi.mock('../components/kanban/KanbanMetrics', ...)   the file is KanbanMetricsBar.tsx
 *     vi.mock('../components/ExportButton', ...)           it lives in components/common
 *
 * **Vitest does not warn about a factory registered for a module nobody imports.** Both were
 * inert, both real components mounted, and the test whose stated purpose is to isolate the
 * page from them was doing no such thing. The suite passed either way — which is exactly why
 * it survived. *A mock that does nothing and a mock that works look identical from the
 * outside.*
 *
 * WHY THAT IS WORSE THAN NO MOCK. A test with no mock is honest about what it renders. A test
 * with a dead mock states an isolation it does not have, so a failure originating in
 * `KanbanMetricsBar` surfaces as a Kanban *page* failure, and the next person debugging it
 * reads the mock list and rules that component out.
 *
 * THIS IS THE FRONTEND TWIN OF FS-484 — a subject list narrower than the code it names — and
 * the third instance of the shape this month: `overlays/dr` absent from the k8s README
 * (FS-520), six alert-test files listed by hand in CI (FS-537). Each artefact was correct
 * when written and wrong the moment something was renamed or added.
 *
 * WHAT IT DOES NOT CHECK: that the factory's shape matches the module's real exports. A mock
 * exporting `{ Foo }` for a module that exports `Bar` is a different defect, caught at import
 * time by the test that uses it — unlike this one, which is caught by nothing.
 */

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOT = resolve(__dirname, '../..')
const SRC = join(ROOT, 'src')

/** Extensions and index forms a relative import may resolve through. */
const RESOLUTIONS = ['', '.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.tsx', '/index.js']

function testFiles(): string[] {
  const found: string[] = []
  const walk = (directory: string) => {
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry)
      if (statSync(path).isDirectory()) walk(path)
      else if (/\.(test|spec)\.(ts|tsx)$/.test(entry)) found.push(path)
    }
  }
  walk(SRC)
  return found
}

/**
 * Source with comments removed.
 *
 * WITHOUT THIS THE GUARD FAILS ON ITS OWN DOCSTRING. The header above quotes the two dead
 * mocks verbatim, so the regex matched them and reported this file as containing two
 * unresolvable paths. `everyMockedClientHasARealModeTest.test.ts` had the identical problem
 * and strips comments for the identical reason.
 *
 * It is rule 37 in its purest form: **a text search matches the comment describing a defect
 * as readily as the defect**, and in this repository the comments are long and quote the
 * broken code exactly. Three of today's guards hit it.
 */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
}

/** `[testFile, specifier]` for every `vi.mock` of a path inside this project. */
function projectMocks(): Array<[string, string]> {
  const mocks: Array<[string, string]> = []
  for (const file of testFiles()) {
    const source = withoutComments(readFileSync(file, 'utf8'))
    for (const match of source.matchAll(/vi\.mock\(\s*['"]([^'"]+)['"]/g)) {
      const specifier = match[1]
      // A bare specifier is a node module — `vi.mock('axios')` is legitimate and its
      // resolution is npm's problem, not this file's.
      if (!specifier.startsWith('.') && !specifier.startsWith('@/')) continue
      mocks.push([file, specifier])
    }
  }
  return mocks
}

function resolves(fromFile: string, specifier: string): boolean {
  const base = specifier.startsWith('@/')
    ? join(SRC, specifier.slice(2))
    : resolve(dirname(fromFile), specifier)
  return RESOLUTIONS.some((extension) => existsSync(base + extension))
}

describe('vi.mock paths resolve', () => {
  it('finds the mocks it is meant to be checking', () => {
    // Vacuity. A regex that matched nothing would pass this file over an empty list while
    // every dead mock in the tree stayed dead — the failure mode this guard exists for,
    // applied to itself.
    const mocks = projectMocks()
    expect(mocks.length).toBeGreaterThan(50)
    expect(testFiles().length).toBeGreaterThan(50)
  })

  it('leaves no mock pointing at a module that does not exist', () => {
    const dead = projectMocks()
      .filter(([file, specifier]) => !resolves(file, specifier))
      .map(([file, specifier]) => `${file.replace(`${ROOT}/`, '')}  ->  ${specifier}`)

    expect(
      dead,
      `these vi.mock calls name a module that does not exist, so vitest registers a factory ` +
        `nobody asks for and the REAL component renders. The test states an isolation it ` +
        `does not have, and a failure originating in that component surfaces here instead — ` +
        `where the mock list rules it out. Vitest does not warn about this and the suite ` +
        `passes either way.`,
    ).toEqual([])
  })

  it('does not read its own documentation as code', () => {
    // The header quotes both dead mocks verbatim. A version of this guard that matched
    // comments reported ITSELF as the offender — and would have gone on doing so, which is
    // the state in which a failing gate gets an exclusion rather than an investigation.
    // The PRECISE property: this file contributes no vi.mock entries to the sweep. An
    // earlier version asserted the stripped source contained no "KanbanMetrics" at all,
    // which failed — the renamed-module test below uses those names as DATA, in code. A
    // self-check that forbids a string is not the same as one that forbids a match.
    const ownEntries = projectMocks().filter(([file]) =>
      file.endsWith('mockPathsResolve.test.ts'),
    )
    expect(
      ownEntries,
      'this guard is reading its own documentation as vi.mock calls. The header quotes both ' +
        'dead mocks verbatim, so a comment-blind regex reports the guard itself as the ' +
        'offender — and a failing gate that blames itself gets an exclusion rather than an ' +
        'investigation.',
    ).toEqual([])
  })

  it('would catch a renamed module', () => {
    // The detector proving itself against the exact shape that happened: KanbanMetricsBar
    // renamed from KanbanMetrics, with the mock left behind.
    const kanbanTest = join(SRC, 'pages/Kanban.test.tsx')
    expect(resolves(kanbanTest, '../components/kanban/KanbanMetricsBar')).toBe(true)
    expect(resolves(kanbanTest, '../components/kanban/KanbanMetrics')).toBe(false)
  })
})
