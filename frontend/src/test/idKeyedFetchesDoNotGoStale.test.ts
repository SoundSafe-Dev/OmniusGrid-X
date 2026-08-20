/**
 * An id-keyed fetch clears, catches and cancels (FS-588).
 *
 * THE CARRY-ACROSS. FS-481 found a list going stale after a filter change. This asks the same
 * question of the **detail** side: when the id changes, what is on screen until the new data
 * arrives — and what happens if it never does?
 *
 * WHAT IT FOUND, and it is money.
 *
 *     useEffect(() => {
 *       transportationApi.getShipmentCosts(shipment.id).then(setCosts)
 *     }, [shipment.id])
 *
 * Three defects in two lines, and all three put one shipment's linehaul, fuel surcharge and
 * total under another shipment's name:
 *
 *   1. **No clear.** Switching from shipment A to B leaves A's figures on screen, under B's
 *      heading, until B's request returns.
 *   2. **No catch.** If B's request fails, A's figures stay there **permanently** — the panel
 *      never stops attributing them to B, and an unhandled rejection is the only trace.
 *   3. **No cancellation.** If A's request is slow and B's is fast, A's response lands second
 *      and overwrites B's. Both requests succeeded and the screen is still wrong.
 *
 * A stale list is a visible annoyance. **A stale cost is a number a dispatcher reads and acts
 * on, and nothing about it looks stale.**
 *
 * REACT QUERY DOES ALL THREE FOR YOU, which is why this class only appears in hand-rolled
 * effects: a query keyed on the id returns `undefined` while fetching, exposes `isError`, and
 * discards a response for a key that is no longer current. The sweep therefore looks only at
 * `useEffect`.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = resolve(__dirname, '..')

/** Effects exempt from one of the three, with why. */
const EXEMPT: Record<string, string> = {}

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry)
    if (statSync(path).isDirectory()) return sourceFiles(path)
    return /\.tsx$/.test(entry) && !/\.(test|spec)\./.test(entry) ? [path] : []
  })
}

/** Comments removed — a comment describing this defect quotes the broken code (rule 37). */
function withoutComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
}

interface Effect {
  file: string
  body: string
  deps: string
}

/** `useEffect`s that fetch and are keyed on an id. */
function idKeyedFetches(): Effect[] {
  const found: Effect[] = []
  for (const file of sourceFiles(SRC)) {
    const source = withoutComments(readFileSync(file, 'utf8'))
    // `useCallback` AS WELL AS `useEffect` (FS-768). The one id-keyed fetch in the tree was
    // lifted out of its effect into a `useCallback` so a failure could offer a Retry — the
    // code is unchanged, the hook around it is not, and this sweep's population fell to ZERO
    // again. That is the second time: the comment below records losing it to a line break.
    //
    // The class is a hand-rolled id-keyed fetch, wherever it is written. Both hooks take the
    // same `(body, deps)` shape, so one alternation covers them.
    const pattern =
      /use(?:Effect|Callback)\(\s*(?:async\s*)?\(\)\s*=>\s*\{([\s\S]{0,1200}?)\},\s*\[([^\]]*)\]\)/g
    for (const match of source.matchAll(pattern)) {
      const [, body, deps] = match
      if (!/\b(?:id|Id)\b/.test(deps)) continue
      // A LAZY IMPORT IS NOT A FETCH. `lazy(() => loader().then(...))` in App.tsx matched an
      // earlier version of this pattern, which is the kind of noise that stops a sweep being
      // read — the `Api.`/`await` requirement is what distinguishes data from code-splitting.
      // WHITESPACE BETWEEN THE RECEIVER AND THE DOT. `Api\.` required them adjacent, and
      // the one id-keyed fetch in the tree is written as a wrapped promise chain:
      //
      //     transportationApi
      //       .getShipmentCosts(shipment.id)
      //
      // so the sweep's population fell to ZERO and every id-keyed detail view in the tree
      // was unchecked. Nothing about the code changed — a line break did. This is the
      // failure the vacuity test above exists for, and the only reason it was noticed.
      if (!/await\s|[Aa]pi\s*\.|\bfetch\s*\(/.test(body)) continue
      found.push({ file: file.replace(`${SRC}/`, ''), body, deps })
    }
  }
  return found
}

const clears = (body: string) => /set\w+\(null\)|set\w+\(\[\]\)|set\w+\(undefined\)/.test(body)
const catches = (body: string) => /\.catch\(|try\s*\{/.test(body)
const cancels = (body: string) => /cancelled|ignore|abort|AbortController|return\s*\(\)\s*=>/.test(body)

describe('an id-keyed fetch clears, catches and cancels', () => {
  it('finds the effects it is meant to be checking', () => {
    // Vacuity. A pattern that matches nothing passes this file over an empty list while
    // every stale detail view in the tree stays stale.
    expect(idKeyedFetches().length).toBeGreaterThan(0)
  })

  it('does not match a lazy import', () => {
    // The false positive an earlier version had. `App.tsx` builds routes with
    // `lazy(() => loader().then(m => …))`, which is code-splitting, not data.
    const flagged = idKeyedFetches().map((e) => e.file)
    expect(flagged).not.toContain('App.tsx')
  })

  it('every id-keyed fetch clears its previous value first', () => {
    const stale = idKeyedFetches()
      .filter((e) => !clears(e.body) && !(e.file in EXEMPT))
      .map((e) => `${e.file}  deps=[${e.deps.trim()}]`)
    expect(
      stale,
      `these effects refetch when an id changes and do not clear what is on screen first, ` +
        `so the PREVIOUS record's data is displayed under the new record's heading until ` +
        `the request returns — and forever if it fails. Set the state to null before the ` +
        `call.`,
    ).toEqual([])
  })

  it('every id-keyed fetch handles a rejection', () => {
    const unhandled = idKeyedFetches()
      .filter((e) => !catches(e.body) && !(e.file in EXEMPT))
      .map((e) => `${e.file}  deps=[${e.deps.trim()}]`)
    expect(
      unhandled,
      `these effects fetch with no catch. The failure is an unhandled rejection in the ` +
        `console and whatever was on screen stays there, attributed to the record that ` +
        `failed to load.`,
    ).toEqual([])
  })

  it('every id-keyed fetch ignores a response for a superseded id', () => {
    const racy = idKeyedFetches()
      .filter((e) => !cancels(e.body) && !(e.file in EXEMPT))
      .map((e) => `${e.file}  deps=[${e.deps.trim()}]`)
    expect(
      racy,
      `these effects do not discard a late response. If the first request is slower than ` +
        `the second, it lands second and overwrites it — both succeeded, and the screen ` +
        `shows the wrong record's data until something else re-renders. Return a cleanup ` +
        `that sets a cancelled flag, or use an AbortController.`,
    ).toEqual([])
  })
})
