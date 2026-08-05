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
const EMAIL = process.env.E2E_USER_EMAIL ?? 'e2e@omniusgrid.test'
const PASSWORD = process.env.E2E_USER_PASSWORD ?? 'e2e-playwright-password'

/** The routes with the most interactive surface, not all 32 — this costs a click each. */
const ROUTES = [
  '/', '/assets', '/alarms', '/kanban', '/logistics/yard',
  '/logistics/transportation', '/erp', '/compliance',
]

const DESTRUCTIVE = /delete|remove|sign out|log ?out|purge|reset|clear all/i

test.describe('controls do not break', () => {
  test.skip(!LIVE, 'needs a live backend; set E2E_LIVE_BACKEND=1')

  test('no control throws or 500s', async ({ page }) => {
    test.setTimeout(240_000)

    const problems: string[] = []
    let route = ''
    page.on('pageerror', (e) => problems.push(`${route}  uncaught: ${String(e).slice(0, 120)}`))
    page.on('response', (r) => {
      if (r.status() >= 500) {
        problems.push(`${route}  HTTP ${r.status()} ${r.url().replace(/^https?:\/\/[^/]+/, '')}`)
      }
    })

    await page.goto('/login')
    await page.getByLabel(/username/i).fill(EMAIL)
    await page.getByLabel(/password/i).fill(PASSWORD)
    await page.getByRole('button', { name: /sign in|log ?in/i }).click()
    await expect(page).not.toHaveURL(/\/login/, { timeout: 20_000 })

    let clicked = 0
    for (const target of ROUTES) {
      route = target
      await page.goto(target).catch(() => {})
      // Wait for a control to exist before counting them. Without this the sweep counts
      // zero and reports a clean run instantly.
      await page.locator('main button').first().waitFor({ timeout: 8000 }).catch(() => {})

      const buttons = page.locator('main button:visible')
      const count = Math.min(await buttons.count().catch(() => 0), 5)
      for (let i = 0; i < count; i++) {
        const label = (await buttons.nth(i).innerText().catch(() => '')) || '(icon)'
        if (DESTRUCTIVE.test(label)) continue
        await buttons.nth(i).click({ timeout: 2000, noWaitAfter: true }).catch(() => {})
        clicked++
      }
    }
    // Requests started by the last clicks need a moment to come back.
    await page.waitForTimeout(1500)

    expect(
      clicked,
      'the sweep clicked nothing, so it reports no problems because it did no work',
    ).toBeGreaterThan(15)

    expect(
      [...new Set(problems)],
      'clicking a control threw or produced a server error',
    ).toEqual([])
  })
})
