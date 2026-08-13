/**
 * A directory of tests no compiler ever reads (FS-684).
 *
 * `tsconfig.json` said `"include": ["src"]`. The six Playwright specs in `e2e/` and their
 * setup project were therefore never typechecked by anything — and `vitest run` does not
 * typecheck either, it transpiles and discards the types.
 *
 * WHAT THAT COST. `e2e/authenticated.spec.ts` referenced `EMAIL`, a name declared in two
 * *other* e2e files and in neither this one. Every execution ended in
 * `ReferenceError: EMAIL is not defined` at the `fill()` — before the click, before the
 * assertion — so the claim that a wrong password does not log you in had never once been
 * checked. The file skips without `E2E_LIVE_BACKEND=1`, so no laptop run ever showed it.
 *
 * Restoring the defect and running `npx tsc --noEmit` now gives
 * `TS2304: Cannot find name 'EMAIL'`. One command, and it would have caught this the day it
 * was written.
 *
 * THIS GUARD IS ABOUT THE CONFIG, NOT THE CODE. The compiler already reports the errors; the
 * only thing that can silently undo that is someone narrowing `include` back — which is
 * exactly the edit that looks harmless in review, because the tests still run and still pass.
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOT = resolve(__dirname, '..', '..')
const TSCONFIG = join(ROOT, 'tsconfig.json')

/** Directories holding TypeScript that must be compiled by someone. */
const MUST_BE_TYPECHECKED = ['src', 'e2e']

function includes(): string[] {
  // Comments are legal in tsconfig and this one has them, so JSON.parse is not an option.
  const raw = readFileSync(TSCONFIG, 'utf8')
  const match = raw.match(/"include"\s*:\s*\[([^\]]*)\]/)
  if (!match) return []
  return [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1])
}

describe('the typecheck reaches every directory of TypeScript we own', () => {
  it('reads an include list at all', () => {
    /** Vacuity: a regex that stops matching would report every directory as missing, and a
     *  regex that matches too much would report none. */
    expect(includes().length).toBeGreaterThan(0)
  })

  it.each(MUST_BE_TYPECHECKED)('covers %s', (dir) => {
    expect(existsSync(join(ROOT, dir)), `${dir} does not exist; update this list`).toBe(true)
    expect(
      includes(),
      `tsconfig.json does not include "${dir}", so nothing typechecks it. ` +
        `vitest transpiles without checking types, and a Playwright spec that skips ` +
        `without a live backend can carry a ReferenceError for years — which is exactly ` +
        `what e2e/authenticated.spec.ts did.`,
    ).toContain(dir)
  })

  it('the e2e directory actually holds specs, so covering it means something', () => {
    /** If the directory emptied out, the assertion above would be true and worthless. */
    const specs = readdirSync(join(ROOT, 'e2e')).filter((f) => f.endsWith('.ts'))
    expect(specs.length).toBeGreaterThanOrEqual(5)
  })

  it('every name a spec uses is one the compiler can see', () => {
    /** THE ASSERTION THIS FILE EXISTS FOR, stated where a reader will look: the guarantee is
     *  delivered by `tsc --noEmit` over the include list above, which `quality-gates.yml`
     *  runs as a blocking step. This test does not re-implement it — a hand-rolled
     *  "undeclared identifier" scanner was tried first and matched every capitalised word in
     *  a comment, which is rule 37 in one line. */
    expect(includes()).toContain('e2e')
  })
})
