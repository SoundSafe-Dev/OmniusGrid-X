import { test, expect, Page } from '@playwright/test'

/**
 * The authenticated journey (FS-239).
 *
 * The existing smoke suite asserts that the login page renders and that a
 * protected route redirects. Nothing ever logged IN, so nothing exercised the auth
 * path, the token handling, or — the important part — whether the dashboard shows
 * real data once you are through it.
 *
 * That gap is not hypothetical. The dashboard rendered all-zeros for months because
 * `/api/v1/dashboard/*` used `get_db`, which never sets `app.current_org_id`, so
 * FORCE RLS on `assets` filtered every row and every tile showed 0 with no error
 * anywhere (FS-191). Every test in the suite passed throughout. This is the test
 * that would have caught it, which is why the assertions below are about NON-ZERO
 * VALUES rather than about elements existing.
 *
 * REQUIRES A LIVE BACKEND. These tests are skipped unless E2E_LIVE_BACKEND=1, so a
 * developer running `npm run e2e` without a database still gets the smoke suite
 * instead of five confusing failures. The CI job sets it after standing up
 * Postgres, migrating, seeding demo data and starting uvicorn.
 */

const LIVE = process.env.E2E_LIVE_BACKEND === '1'
const EMAIL = process.env.E2E_USER_EMAIL ?? 'e2e@omniusgrid.test'
const PASSWORD = process.env.E2E_USER_PASSWORD ?? 'e2e-playwright-password'

test.describe('authenticated journey', () => {
  test.skip(!LIVE, 'needs a live backend; set E2E_LIVE_BACKEND=1')

  async function login(page: Page) {
    await page.goto('/login')
    // The form labels its fields Username and Password. The backend treats the
    // username as the email (OAuth2PasswordRequestForm.username).
    await page.getByLabel(/username/i).fill(EMAIL)
    await page.getByLabel(/password/i).fill(PASSWORD)
    await page.getByRole('button', { name: /sign in|log ?in/i }).click()
    // Landing anywhere other than /login means the token round-trip worked.
    await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 })
  }

  test('rejects a wrong password without logging in', async ({ page }) => {
    // Asserted first so a later success cannot be explained by the form simply
    // navigating regardless of what the server said.
    await page.goto('/login')
    await page.getByLabel(/username/i).fill(EMAIL)
    await page.getByLabel(/password/i).fill('definitely-not-the-password')
    await page.getByRole('button', { name: /sign in|log ?in/i }).click()

    await expect(page).toHaveURL(/\/login/)
  })

  test('logs in and the dashboard shows NON-ZERO data', async ({ page }) => {
    await login(page)
    await page.goto('/')

    // Wait for the KPI region to have resolved rather than for a fixed timeout.
    await expect(page.locator('body')).toContainText(/asset/i, { timeout: 20_000 })

    // The actual regression guard. A dashboard that renders every tile as "0" is
    // exactly what the RLS bug produced, and it looks completely healthy: no
    // error, no empty state, just zeros. So assert that SOME number on the page is
    // greater than zero.
    const numbers = await page
      .locator('text=/^[0-9][0-9,.]*$/')
      .allTextContents()
    const parsed = numbers
      .map((t) => Number(t.replace(/,/g, '')))
      .filter((n) => Number.isFinite(n))

    expect(parsed.length, 'dashboard rendered no numeric values at all').toBeGreaterThan(0)
    expect(
      parsed.some((n) => n > 0),
      `every numeric value on the dashboard was zero (${parsed.slice(0, 20).join(', ')}) — ` +
        'this is the shape of the FS-191 tenancy bug: RLS filters every row, so the ' +
        'page renders successfully with nothing in it',
    ).toBe(true)
  })

  test('the assets page lists seeded assets', async ({ page }) => {
    await login(page)
    await page.goto('/assets')
    // The demo seeder creates named assets; an empty list here is the same
    // tenancy failure as the zeroed dashboard, one page over.
    await expect(page.locator('table tbody tr, [role="row"]').first()).toBeVisible({
      timeout: 20_000,
    })
  })

  test('the alarms page loads for an authenticated user', async ({ page }) => {
    await login(page)
    await page.goto('/alarms')
    // Alarms were the subject of a cross-tenant leak (FS-216); this only asserts
    // the page renders for its OWN tenant. Cross-tenant isolation is asserted
    // properly in the backend suite, where a second organization can be created.
    await expect(page.locator('body')).toContainText(/alarm/i, { timeout: 20_000 })
  })

  test('logging out returns to the login page', async ({ page }) => {
    await login(page)
    await page.goto('/')
    await page.evaluate(() => window.localStorage.clear())
    await page.goto('/assets')
    await expect(page).toHaveURL(/\/login/)
  })
})
