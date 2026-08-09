/**
 * Every routed page has a unit test file, resolved THROUGH the barrel (FS-483).
 *
 * FS-364 recorded eight routed pages with no test at all. Closing it needed a way to ask
 * "which are left?", and the obvious way is to read the lazy imports out of `App.tsx` and
 * look for a sibling `.test.tsx`. That walk reported zero remaining — twice — while `Fleet`
 * (574 lines) and `ErrorTriage` (371) had no test.
 *
 * **Both are imported through a barrel.** The route reads:
 *
 *     const Fleet = named(() => import('./pages/admin'), 'Fleet')
 *
 * so the string `pages/admin/Fleet` appears nowhere, and a resolver keyed on the import path
 * goes looking for a test beside the barrel DIRECTORY rather than beside the page, does not
 * find a page there either, and reports nothing missing. "None left" is the answer nobody
 * re-checks, which is what makes a walk that under-reports worse than no walk.
 *
 * So this one follows the `named(loader, 'Export')` form into `pages/<dir>/index.ts` and
 * resolves which module actually exports that name. The vacuity tests below assert that it
 * resolves a known barrel page and that it reads a plausible number of routes — because a
 * broken resolver returns an empty list, and an empty list passes.
 *
 * WHAT IT DOES NOT CLAIM. A test file is not coverage. This asks only whether somebody has
 * written *something* against each routed page; what that file asserts is the reviewer's
 * problem. The bar is low on purpose — the pages this caught had no file at all, which is a
 * different situation from a thin one.
 */
import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { resolve, join } from 'node:path'

const ROOT = resolve(__dirname, '../..')
const SRC = resolve(ROOT, 'src')

/** Components actually mounted by a `<Route element={<X />} />`. A lazily-imported page that
 *  no route renders is dead code, not an untested page. */
function routedComponents(app: string): string[] {
  return [...app.matchAll(/element=\{<([A-Z]\w*)\s*\/>\}/g)].map((m) => m[1])
}

/** `X` -> the module path its lazy import names, for both forms App.tsx uses. */
function importPaths(app: string): Map<string, { path: string; exported?: string }> {
  const map = new Map<string, { path: string; exported?: string }>()
  for (const m of app.matchAll(/const (\w+) = lazy\(\(\) => import\('([^']+)'\)\)/g)) {
    map.set(m[1], { path: m[2] })
  }
  for (const m of app.matchAll(/const (\w+) = named\(\(\) => import\('([^']+)'\), '(\w+)'\)/g)) {
    map.set(m[1], { path: m[2], exported: m[3] })
  }
  return map
}

/** Follow `pages/<dir>/index.ts` to the file that really exports `name`.
 *
 * The barrel re-exports under aliases (`UsersPage as Users`), so both the local name and the
 * alias have to be matched or the four AdminPages routes resolve to nothing and silently
 * drop out of the check. */
function throughBarrel(dir: string, name: string): string | null {
  const barrel = ['index.ts', 'index.tsx'].map((f) => join(dir, f)).find(existsSync)
  if (!barrel) return null
  const source = readFileSync(barrel, 'utf8')
  for (const m of source.matchAll(/export\s*\{([^}]*)\}\s*from\s*'([^']+)'/g)) {
    const exports = m[1].split(',').map((s) => s.trim())
    const hit = exports.some((e) => {
      const [local, alias] = e.split(/\s+as\s+/).map((s) => s.trim())
      return (alias ?? local) === name
    })
    if (hit) return resolve(dir, m[2] + '.tsx')
  }
  return null
}

/** The source file backing a routed component, or null if it cannot be resolved. */
export function pageFileFor(app: string, component: string): string | null {
  const entry = importPaths(app).get(component)
  if (!entry) return null
  const base = resolve(SRC, entry.path.replace(/^\.\//, ''))
  const direct = base + '.tsx'
  if (existsSync(direct)) return direct
  if (entry.exported) return throughBarrel(base, entry.exported)
  return null
}

const APP = readFileSync(resolve(SRC, 'App.tsx'), 'utf8')
const RESOLVED = routedComponents(APP)
  .map((c) => ({ component: c, file: pageFileFor(APP, c) }))
  .filter((r): r is { component: string; file: string } => r.file !== null)

/** A page counts as tested if a `.test.tsx` sits beside it under its own name. Several
 *  routes share one module — the four AdminPages routes are one file — and one test file
 *  beside that module covers all of them, which the sibling rule already handles. */
const UNTESTED = RESOLVED.filter(
  ({ file }) => !existsSync(file.replace(/\.tsx$/, '.test.tsx')),
)

describe('the resolver is not vacuous', () => {
  it('finds a plausible number of routed pages', () => {
    // A broken regex resolves nothing, and nothing passes every check below.
    expect(RESOLVED.length).toBeGreaterThan(20)
  })

  it('resolves a page imported directly', () => {
    expect(pageFileFor(APP, 'Kanban')).toBe(resolve(SRC, 'pages/Kanban.tsx'))
  })

  it('resolves a page imported through a barrel', () => {
    // THE CASE THIS FILE EXISTS FOR. A resolver that cannot do this reports "none left"
    // while two of the largest pages in the app have no test.
    expect(pageFileFor(APP, 'Fleet')).toBe(resolve(SRC, 'pages/admin/Fleet.tsx'))
  })

  it('resolves a barrel export renamed on the way out', () => {
    // `UsersPage as Users`, and since 2026-08-08 the page lives in Users.tsx rather than
    // AdminPages.tsx. The rename is what this asserts; the file it points at moved with
    // the merge that split the page out.
    expect(pageFileFor(APP, 'Users')).toBe(resolve(SRC, 'pages/admin/Users.tsx'))
  })
})

describe('every routed page has a test file', () => {
  it('has none without one', () => {
    expect(
      UNTESTED.map(
        (u) =>
          `${u.component} (${u.file.slice(SRC.length + 1)}) is mounted by a route and has ` +
          `no test file — FS-364's list, which a walk that could not follow barrel imports ` +
          `twice reported as empty`,
      ),
    ).toEqual([])
  })
})
