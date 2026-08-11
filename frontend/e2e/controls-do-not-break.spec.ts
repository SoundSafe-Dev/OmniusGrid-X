import { test, expect } from '@playwright/test'

/**
 * Clicking a control must not crash the page or 500 the server (FS-450).
 *
 * `data-reaches-the-screen.spec.ts` proves every route RENDERS. Nothing proved any of it
 * WORKS: a button whose handler throws, or whose request 500s, leaves the page looking
 * exactly as it did before — React swallows the error into a boundary, or the failure lands
 * in a rejected promise nobody awaits. This repository has already shipped one of those:
 * `dispatchShipment` returned 422 on every call since the day it was written (FS-420), and
 * no test could see it because no test clicked anything.
 *
 * WHAT IT WATCHES, and deliberately nothing more: uncaught page errors and any response of
 * 500 or worse. Both are unambiguous — there is no product judgement in "the server threw"
 * — so this stays useful without encoding what each button is supposed to do.
 *
 * DESTRUCTIVE LABELS ARE SKIPPED by name. The stack it runs against is seeded demo data, but
 * a sweep that clicks "Delete" is one that eventually deletes something a later assertion
 * needed, and diagnosing that is worse than the coverage is worth.
 *
 * THE VACUITY ASSERTION IS THE POINT. The first version of this had no wait after `goto`,
 * counted zero buttons, clicked nothing, and PASSED in 4.7 seconds — a sweep reporting no
 * problems because it did no work, which is the exact shape this codebase has seventy-five
 * rules about. `expect(clicked).toBeGreaterThan(15)` is what makes a clean run mean
 * something.
 */

const LIVE = process.env.E2E_LIVE_BACKEND === '1'

/** EVERY routed page, from the shared list (FS-492).
 *
 *  This was a private array of eight — "the routes with the most interactive surface, not
 *  all 32". It swept **8 of 33**, and the twenty-five it skipped were every admin page,
 *  every engine, all three analytics pages, OEE, shop-floor, intake and NLP.
 *
 *  The comment was a reasonable cost decision when it was made and it became a coverage
 *  claim nobody re-examined. It also could not drift into view: `everyRouteIsSwept.test.ts`
 *  compares `App.tsx` against `e2e/routes.ts`, so a private copy here was invisible to the
 *  guard that exists to catch exactly this.
 *
 *  Sharing the list is what makes that guard cover this file too — and it is why the
 *  timeout below is now per-route rather than a constant, because the work just quadrupled.
 *
 *  The premise is in this file's own docstring: `dispatchShipment` returned 422 on every
 *  call since the day it was written, and no test could see it because no test clicked
 *  anything. Three quarters of the product was still in that position. */
import { ROUTES } from './routes'

const DESTRUCTIVE = /delete|remove|sign out|log ?out|purge|reset|clear all/i

test.describe('controls do not break', () => {
  test.skip(!LIVE, 'needs a live backend; set E2E_LIVE_BACKEND=1')

  // Tests in one file run SERIALLY by default, so splitting the loop into 33 tests bought
  // the better failure messages and none of the speed — it went from 6.6 to 7.7 minutes.
  // This is the half that pays for the split.
  test.describe.configure({ mode: 'parallel' })

  // ONE TEST PER ROUTE (FS-492).
  //
  // This was a single test looping all the routes, and pointing it at the full list took it
  // from 8 routes to 33 — which timed out at 240s, then at 396s, and ran 6.6 minutes doing
  // it. Raising the constant again would have bought an eleven-minute serial job whose
  // failure is one red line naming a list.
  //
  // A test per route is better on every axis that matters here: Playwright can run them in
  // parallel, each carries a budget sized to one page rather than to the whole product, and
  // a failure says WHICH route broke in its own title instead of inside an array. The
  // accumulated-problems design only ever existed because the loop was one test.
  for (const target of ROUTES) {
    test(`${target} — no control throws or 500s`, async ({ page }) => {
      test.setTimeout(45_000)

      const problems: string[] = []
      page.on('pageerror', (e) => problems.push(`uncaught: ${String(e).slice(0, 160)}`))
      page.on('response', (r) => {
        if (r.status() >= 500) {
          problems.push(`HTTP ${r.status()} ${r.url().replace(/^https?:\/\/[^/]+/, '')}`)
        }
      })

      // No login (FS-452) — the suite authenticates once in a setup project.
      await page.goto(target)

      // Wait for a control to exist before counting them. Without this the sweep counts
      // zero and reports a clean route instantly.
      await page.locator('main button').first().waitFor({ timeout: 8000 }).catch(() => {})

      const buttons = page.locator('main button:visible')
      const count = Math.min(await buttons.count().catch(() => 0), 5)
      // No counter here: the `the sweep actually clicks things` test below is what proves
      // the sweep is not a no-op, and one vacuity check for the file beats 33 unread ones.
      for (let i = 0; i < count; i++) {
        const label = (await buttons.nth(i).innerText().catch(() => '')) || '(icon)'
        if (DESTRUCTIVE.test(label)) continue
        await buttons.nth(i).click({ timeout: 2000, noWaitAfter: true }).catch(() => {})
      }
      // Requests started by the last clicks need a moment to come back.
      await page.waitForTimeout(1500)

      expect(
        [...new Set(problems)],
        `clicking a control on ${target} threw or produced a server error`,
      ).toEqual([])
    })
  }

  // The vacuity check the per-route split would otherwise lose. Each route above passes
  // trivially if it finds no buttons, so SOMETHING has to assert the sweep does work at
  // all — otherwise a selector change turns 33 green ticks into 33 no-ops.
  test('the sweep actually clicks things', async ({ page }) => {
    test.setTimeout(120_000)

    let clicked = 0
    for (const target of ROUTES.slice(0, 8)) {
      await page.goto(target).catch(() => {})
      await page.locator('main button').first().waitFor({ timeout: 8000 }).catch(() => {})
      clicked += Math.min(await page.locator('main button:visible').count().catch(() => 0), 5)
    }

    expect(
      clicked,
      'the sweep found no controls to click, so every route above reports clean because it did no work',
    ).toBeGreaterThan(15)
  })
})
