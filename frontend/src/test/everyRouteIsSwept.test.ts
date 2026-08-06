/**
 * Every routed page is in the e2e sweep (FS-449).
 *
 * `data-reaches-the-screen.spec.ts` walks a list of routes asserting that none renders
 * `undefined`, `NaN`, `[object Object]` or `Invalid Date` — the visible signature of a field
 * that was declared, read by a template, and never sent.
 *
 * **A hand-maintained list of routes drifts the moment someone adds a page,** and the page
 * nobody added is exactly the one that goes unchecked. That is not hypothetical here: the
 * four defects this sweep was written for were all on pages nobody thought to check, and the
 * list started as nine hand-picked routes out of thirty-two.
 *
 * This runs in the frontend unit suite rather than as an e2e test, deliberately: it needs no
 * browser and no backend, so it fires on every push instead of only where Playwright and a
 * live stack are available. The sweep it guards is the expensive one; this is the cheap
 * thing that keeps the expensive one honest.
 */

import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const ROOT = resolve(__dirname, '../..')

function declaredRoutes(): string[] {
  const app = readFileSync(resolve(ROOT, 'src/App.tsx'), 'utf8')
  return [...app.matchAll(/path="(\/[a-z0-9/-]*)"/g)]
    .map((m) => m[1])
    .filter((p) => p !== '/login')
}

function sweptRoutes(): string[] {
  // `e2e/routes.ts`, not the spec that used to hold it: Playwright refuses spec-to-spec
  // imports, and a second spec needed the same list — so it moved to a shared module
  // (FS-489). Reading the old path would leave this comparison over an empty array.
  const spec = readFileSync(resolve(ROOT, 'e2e/routes.ts'), 'utf8')
  const block = spec.match(/export const ROUTES = \[([\s\S]*?)\]/)
  if (!block) throw new Error('the ROUTES array could not be found in the e2e spec')
  return [...block[1].matchAll(/'([^']+)'/g)].map((m) => m[1])
}

describe('the route sweep is not vacuous', () => {
  it('reads a plausible number of routes from App.tsx', () => {
    // If the regex drifts this returns nothing and the comparison below passes over two
    // empty lists — the failure every sweep in this repository has a rule about.
    expect(declaredRoutes().length).toBeGreaterThan(25)
  })

  it('reads the list out of the spec', () => {
    expect(sweptRoutes().length).toBeGreaterThan(25)
  })
})

describe('every routed page is swept', () => {
  it('has no route that the e2e sweep misses', () => {
    const missing = declaredRoutes().filter((r) => !sweptRoutes().includes(r))
    expect(
      missing,
      `these routes exist in App.tsx and are not in the e2e sweep, so nothing checks ` +
        `whether they render a field that never arrived: ${missing.join(', ')}`,
    ).toEqual([])
  })

  it('sweeps no route that no longer exists', () => {
    // The other direction. A route removed from the app but left in the list means one
    // sweep entry silently navigates to the 404 page, which contains no `undefined` and
    // passes while asserting nothing — the exact trap that put `/maintenance` in the first
    // draft of this list.
    const declared = declaredRoutes()
    const stale = sweptRoutes().filter((r) => !declared.includes(r))
    expect(
      stale,
      `these routes are swept and no longer exist in App.tsx, so each navigates to the 404 ` +
        `page and asserts nothing: ${stale.join(', ')}`,
    ).toEqual([])
  })
})
