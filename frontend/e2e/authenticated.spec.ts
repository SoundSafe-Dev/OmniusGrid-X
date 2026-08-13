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

/** THE WRONG-PASSWORD TEST BELOW HAD NEVER RUN (FS-683).
 *
 * It referenced `EMAIL` and nothing in this file defined or imported it, so every execution
 * ended in `ReferenceError: EMAIL is not defined` at the fill() — before the click, before
 * the assertion. The name is a local `const` in `auth.setup.ts` and in
 * `writes-actually-persist.spec.ts`, which is why it reads as though it were in scope.
 *
 * It skips without a live backend, so it is invisible on a laptop; with one, it fails for a
 * reason that looks like a broken selector rather than a test that was never wired. The
 * claim it makes — that a wrong password does not log you in — is one nobody would want to
 * take on trust, and it has been taking exactly that. */
const EMAIL = process.env.E2E_USER_EMAIL ?? 'e2e@omniusgrid.test'

test.describe('authenticated journey', () => {
  test.skip(!LIVE, 'needs a live backend; set E2E_LIVE_BACKEND=1')

  /** No login here (FS-452) — the suite authenticates once in a setup project. */
  async function login(page: Page) {
    await page.goto('/')
    await expect(page).not.toHaveURL(/\/login/, { timeout: 20_000 })
  }

  test('rejects a wrong password without logging in', async ({ page }) => {
    // Asserted first so a later success cannot be explained by the form simply
    // navigating regardless of what the server said.
    //
    // EXPLICITLY LOGGED OUT (FS-452). The suite now inherits an authenticated session from
    // the setup project, and this test is about what happens to someone who is NOT signed
    // in. It would still distinguish — a successful login navigates, a rejected one does
    // not — but a test named "without logging in" that runs while logged in is one whose
    // meaning a reader has to reconstruct.
    await page.goto('/login')
    await page.evaluate(() => window.localStorage.clear())
    await page.goto('/login')
    await page.getByLabel(/username/i).fill(EMAIL)
    await page.getByLabel(/password/i).fill('definitely-not-the-password')
    const rejected = page.waitForResponse(
      (r) => r.url().includes('/auth/login') && r.request().method() === 'POST',
    )
    await page.getByRole('button', { name: /sign in|log ?in/i }).click()

    // WAIT FOR THE SERVER TO ANSWER BEFORE ASSERTING ANYTHING (FS-683, second half).
    //
    // The original assertion was `await expect(page).toHaveURL(/\/login/)` immediately
    // after the click, and `toHaveURL` passes the moment it matches. A quarter-second
    // after clicking, the URL is still /login whatever the server is about to say — so the
    // test passed for a CORRECT password too, which is how it was caught. Proven directly:
    // a probe that submitted the real credentials watched the app navigate to `/`, while
    // this assertion had already been satisfied by the pre-navigation state.
    //
    // A rejection is now identified by the two things only a rejection produces: a
    // non-2xx from the login endpoint, and the error the page renders because of it.
    const response = await rejected
    expect(response.status(), 'the server accepted a password that should be wrong').toBe(401)

    await expect(page.getByText(/invalid|incorrect|failed|unauthor/i).first()).toBeVisible({
      timeout: 10_000,
    })
    await expect(page).toHaveURL(/\/login/)
  })

  test('logs in and the dashboard shows NON-ZERO data', async ({ page }) => {
    await login(page)
    await page.goto('/')

    // WAIT FOR THE KPI REGION, not for the word "asset" (FS-447). This waited on
    // `body` containing /asset/i — which the SIDEBAR's "Assets" nav link satisfies the
    // instant the shell mounts, before any query resolves. The test then read the page and
    // found no numbers, failing with "dashboard rendered no numeric values at all" against
    // an API returning `total_assets: 5`.
    //
    // A wait that is satisfied by furniture is not a wait. `Total Assets` is a KPI label
    // rendered only by the dashboard itself, and the value beside it is what this test is
    // actually about.
    await expect(page.getByText('Total Assets')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText('—').first()).toBeHidden({ timeout: 20_000 }).catch(() => {})

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
    // A CARD GRID, not a table (FS-447). This asserted
    // `table tbody tr, [role="row"]`, and `Assets.tsx` renders
    // `<div className="grid …">` of `<Link>` cards — there is no table and no row role
    // anywhere on the page, so the locator could never match and the assertion could only
    // ever fail. Found by running it against a live stack for the first time.
    //
    // Asserting a seeded NAME rather than a container is also the stronger check and the
    // one this file argues for elsewhere: an empty grid and a grid of cards rendering
    // `undefined` are both "rows exist" to a structural selector.
    await expect(page.getByText(/CNC Mill|Conveyor|Acoustic Monitor/).first()).toBeVisible({
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
