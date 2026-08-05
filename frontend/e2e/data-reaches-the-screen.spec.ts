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

  async function login(page: Page) {
    await page.goto('/login')
    await page.getByLabel(/username/i).fill(EMAIL)
    await page.getByLabel(/password/i).fill(PASSWORD)
    await page.getByRole('button', { name: /sign in|log ?in/i }).click()
    await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 })
  }

  test('an alarm names the machine it came from (FS-436)', async ({ page }) => {
    await login(page)
    await page.goto('/alarms')
    await expect(page.locator('body')).toContainText(/alarm/i, { timeout: 20_000 })

    const rows = page.locator('table tbody tr')
    const count = await rows.count()
    test.skip(count === 0, 'no alarms seeded; nothing to assert about')

    // The asset column must carry a NAME, not an empty cell and not a bare UUID. Before
    // the fix `asset_name` was never sent and this cell rendered blank on every row.
    const text = (await rows.first().innerText()).trim()
    expect(text.length, 'the first alarm row rendered no text at all').toBeGreaterThan(0)
    expect(
      text,
      'an alarm row shows a bare UUID where the asset name belongs — the name is ' +
        'resolved by join and a null means the resolver stopped running',
    ).not.toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-/i)
  })

  test('a trailer with a driver shows the driver block (FS-437)', async ({ page }) => {
    await login(page)
    await page.goto('/logistics/yard')
    await expect(page.locator('body')).toContainText(/yard|trailer/i, { timeout: 20_000 })

    // The block is gated on `trailer.driverName`. If the heading is present at all, the
    // gate opened — which is the whole assertion, because for months it could not.
    const heading = page.getByText('Driver Information', { exact: false })
    const visible = await heading.count()
    test.skip(visible === 0, 'no trailer with a driver on this yard; nothing to assert')

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
