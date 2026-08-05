import { test, expect, Page } from '@playwright/test'

/**
 * A field that arrives must reach the screen (FS-443).
 *
 * Four defects this week were the same shape, and NO existing instrument could see any of
 * them. The server sent the data, the response model declared it, the TypeScript compiled,
 * every backend test passed — and the screen showed nothing:
 *
 *   FS-436  the dashboard's alarm rows rendered `{assetName} • {time}` and nothing had ever
 *           sent `assetName`, so every row was a bullet with an empty space in front of it
 *   FS-437  the yard's whole driver block was gated on `{trailer.driverName && …}`, which
 *           was never sent — so the block never rendered, taking `driverPhone` with it, a
 *           field a resolver existed specifically to deliver
 *   FS-439  the shipment panel rendered `{shipment.vehicleId || 'Not assigned'}` and
 *           `shipments` has no vehicle column, so every shipment read "Not assigned"
 *   FS-435  a yard move's mover and both its times arrived under names no alias mapped
 *
 * A backend test asserts the API sends the field. A type-checker asserts the field is
 * declared. Neither can see the gap between them, and that gap is where all four lived.
 * **Only a browser looking at the rendered page can.**
 *
 * WHY VALUES, NOT ELEMENTS. `authenticated.spec.ts` set this precedent for a good reason —
 * the FS-191 tenancy bug rendered a complete, error-free dashboard of zeros. Asserting an
 * element exists would have passed. So these assert what is IN the elements.
 *
 * THE LAST TEST IS THE GENERAL ONE. `undefined`, `NaN`, `[object Object]` and `Invalid Date`
 * are the visible signature of a field that did not arrive, whatever the field. It costs one
 * page load per route and catches defects nobody has found yet.
 *
 * REQUIRES A LIVE BACKEND, same gate and same reason as the authenticated journey: without
 * one these assert nothing, and five confusing failures on a laptop teach people to ignore
 * the suite.
 */

const LIVE = process.env.E2E_LIVE_BACKEND === '1'
const EMAIL = process.env.E2E_USER_EMAIL ?? 'e2e@omniusgrid.test'
const PASSWORD = process.env.E2E_USER_PASSWORD ?? 'e2e-playwright-password'

/** The visible signature of a field that never arrived. */
const NOT_ARRIVED = /\bundefined\b|\bNaN\b|\[object Object\]|Invalid Date/

test.describe('data reaches the screen', () => {
  test.skip(!LIVE, 'needs a live backend; set E2E_LIVE_BACKEND=1')

  /**
   * ONE LOGIN FOR THE WHOLE FILE (FS-447). Every test logging in separately meant twelve
   * logins here plus five next door, against `AUTH_LOGIN_RATE_LIMIT = 10/minute` — which
   * compose turns ON by default. Two tests failed on a login TIMEOUT rather than on
   * anything they assert, and which two depended on worker scheduling.
   *
   * A rate limiter is not a flake: it is the server correctly refusing the seventeenth
   * login in a minute. Retrying would have hidden it and made the suite slower.
   *
   * The token is captured once and replayed into localStorage before each test, which is
   * the standard Playwright storage-state pattern and removes eleven round trips.
   */
  let storage: { origins: unknown[]; cookies: unknown[] } | null = null

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage()
    await page.goto('/login')
    await page.getByLabel(/username/i).fill(EMAIL)
    await page.getByLabel(/password/i).fill(PASSWORD)
    await page.getByRole('button', { name: /sign in|log ?in/i }).click()
    await expect(page).not.toHaveURL(/\/login/, { timeout: 20_000 })
    storage = (await page.context().storageState()) as typeof storage
    await page.close()
  })

  async function login(page: Page) {
    if (!storage) throw new Error('the shared login never completed')
    await page.context().addCookies((storage.cookies ?? []) as never)
    // The SPA keeps its token in localStorage, so the origin state is what matters.
    await page.goto('/login')
    await page.evaluate((state) => {
      for (const origin of (state as any).origins ?? []) {
        for (const item of origin.localStorage ?? []) {
          window.localStorage.setItem(item.name, item.value)
        }
      }
    }, storage)
    await page.goto('/')
    await expect(page).not.toHaveURL(/\/login/, { timeout: 20_000 })
  }

  test('an alarm names the machine it came from (FS-436)', async ({ page }) => {
    await login(page)
    await page.goto('/alarms')
    await expect(page.locator('body')).toContainText(/alarm/i, { timeout: 20_000 })

    // NOT `table tbody tr` (FS-448). `Alarms.tsx` renders a div list, so that locator
    // matched nothing — and because the guard below was `test.skip(count === 0)`, a
    // selector that could never match turned into a SILENT SKIP rather than a failure.
    // The assertion sat inert and green for as long as it existed, which is worse than a
    // red one: nothing was ever going to tell me.
    //
    // Asserting the seeded asset NAME instead. `/api/v1/alarms/` has sent `asset_name`
    // since FS-436; until FS-448 the page received it and rendered the alarm code alone,
    // so an operator could see that something was wrong and not which machine.
    await expect(
      page.getByText(/CNC Mill|Conveyor|Vibration Sensor/).first(),
      'no alarm row names its machine — `asset_name` is resolved by join on /alarms/, so ' +
        'either the resolver stopped running or the page stopped rendering it',
    ).toBeVisible({ timeout: 20_000 })
  })

  test('a trailer with a driver shows the driver block (FS-437)', async ({ page }) => {
    await login(page)
    await page.goto('/logistics/yard')
    await expect(page.locator('body')).toContainText(/yard|trailer/i, { timeout: 20_000 })

    // OPEN A TRAILER FIRST (FS-448). The driver block lives in the DETAIL panel, which
    // renders only once a trailer row is clicked — so asserting on the list page found no
    // heading and `test.skip(count === 0)` turned that into a silent pass. The test was
    // inert for the same reason the alarm one was: a skip guard in front of a locator that
    // could not match.
    // A TRAILER THAT HAS A DRIVER, named explicitly. `.first()` picked whichever row the
    // list happened to order first — which is the trailer with no driver, so the block
    // correctly did not render and the test failed for the right reason about the wrong
    // trailer. TRL-4482 is the detention case in the demo seed, and detention is exactly
    // when someone needs the driver's number.
    const row = page.locator('tbody tr').filter({ hasText: 'TRL-4482' })
    await expect(
      row,
      'the seeded detention trailer TRL-4482 is not on the yard; the demo data changed ' +
        'and this assertion is now about nothing',
    ).toBeVisible({ timeout: 20_000 })
    await row.click()

    // The block is gated on `trailer.driverName`. If the heading is present at all, the
    // gate opened — which is the whole assertion, because for months it could not.
    const heading = page.getByText('Driver Information', { exact: false })
    await expect(
      heading,
      'the driver block did not render for a trailer that has a driver. It is gated on ' +
        '`trailer.driverName`, so this is the gate closed again — and it takes ' +
        '`driverPhone` with it, the number an operator calls about a dwelling trailer',
    ).toBeVisible({ timeout: 15_000 })

    // And the phone that lives INSIDE the gated block must be reachable, which is the
    // half that was invisible: the resolver delivered it and the gate hid it.
    const block = heading.first().locator('..')
    await expect(block).not.toContainText(NOT_ARRIVED)
  })

  test('a shipment shows its trailer, not a vehicle it never had (FS-439)', async ({ page }) => {
    await login(page)
    await page.goto('/logistics/transportation')
    await expect(page.locator('body')).toContainText(/shipment|carrier/i, { timeout: 20_000 })

    // `shipments` has no vehicle column and never had one, so the panel used to render
    // "Not assigned" under a Vehicle heading for EVERY shipment — a statement, not a blank.
    await expect(
      page.getByText('Vehicle', { exact: true }),
      'a "Vehicle" label is back on the shipment panel; shipments reference a TRAILER, ' +
        'and the vehicle field could only ever render "Not assigned"',
    ).toHaveCount(0)
  })

  /**
   * The general case. Each of the four defects above was found by hand, one at a time,
   * after shipping. These four strings are what such a field looks like once it reaches a
   * template, and checking for them costs one page load per route.
   */
  // EVERY ROUTE HERE EXISTS IN App.tsx — checked, because a typo'd path renders the 404
  // page, which trivially contains no "undefined" and passes while asserting nothing.
  // `/maintenance` was in the first draft of this list and is not a route; the real one is
  // `/analytics/maintenance`.
  for (const route of [
    '/',
    '/assets',
    '/alarms',
    '/logistics/yard',
    '/logistics/transportation',
    '/oee',
    '/analytics/maintenance',
    '/predictive/rul',
    '/fleet',
  ]) {
    test(`no field renders as undefined on ${route}`, async ({ page }) => {
      await login(page)
      await page.goto(route)
      // Settled, not a fixed wait: something must have rendered before absence means
      // anything. An empty page trivially contains no "undefined".
      await expect(page.locator('main, body')).not.toBeEmpty({ timeout: 20_000 })
      await page.waitForLoadState('networkidle').catch(() => {})

      const body = await page.locator('body').innerText()
      const match = body.match(NOT_ARRIVED)
      expect(
        match,
        `${route} renders ${match?.[0] ?? ''} — the visible signature of a field that ` +
          `was declared, read by a template, and never sent. Context: ` +
          `${body.slice(Math.max(0, (match?.index ?? 0) - 80), (match?.index ?? 0) + 80)}`,
      ).toBeNull()
    })
  }
})
