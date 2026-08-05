import { test, expect, Page, APIRequestContext } from '@playwright/test'

/**
 * A write driven through the UI must actually land (FS-451).
 *
 * All 44 existing e2e tests READ. Every create, edit and dispatch path in the product is
 * covered only by backend tests that call the API directly — which means nothing exercises
 * the payload **the UI assembles**, and that is where the failures have been:
 *
 *   FS-420  `dispatchShipment` returned 422 on EVERY CALL since the day it was written,
 *           because the client sent a field the endpoint read as a query parameter — and
 *           its picker offered a vehicle for a trailer foreign key
 *   FS-418  one click on "add platform data" broke a correlation session permanently
 *   FS-379  a bare non-Pydantic parameter on a POST is a QUERY parameter, and the client
 *           sent it in the body
 *
 * Each is a mismatch between what the form collects and what the endpoint accepts. A backend
 * test constructs a correct payload by hand and passes; a component test mocks the client
 * and passes. **Only a browser filling the real form finds them.**
 *
 * WHAT EACH TEST ASSERTS. Not that the button was clicked, and not that a success toast
 * appeared — the FS-420 form rendered no error at all while every submission 422'd. Each
 * checks the artefact through the API afterwards: the row exists, with the values typed
 * into the form. A write is not a write until something else can see it.
 *
 * WHY SHOP FLOOR. It is the write-heaviest surface in the product (eight mutations), every
 * one of them fans out to a system of record, and a posting that never lands is exactly the
 * kind of absence that looks like success — the ledger simply stays empty.
 */

const LIVE = process.env.E2E_LIVE_BACKEND === '1'
const EMAIL = process.env.E2E_USER_EMAIL ?? 'e2e@omniusgrid.test'
const PASSWORD = process.env.E2E_USER_PASSWORD ?? 'e2e-playwright-password'
const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8000'

/** A value unique to this run, so an assertion cannot pass on a row from a previous one. */
const STAMP = `E2E-${Date.now().toString(36).toUpperCase()}`

test.describe('writes actually persist', () => {
  test.skip(!LIVE, 'needs a live backend; set E2E_LIVE_BACKEND=1')

  let token = ''

  test.beforeAll(async ({ playwright }) => {
    // A direct API login for the ASSERTIONS, separate from the browser session that does
    // the writing. Reading back through the same client that wrote would prove only that
    // the client is self-consistent.
    const api: APIRequestContext = await playwright.request.newContext()
    const response = await api.post(`${API}/api/v1/auth/login`, {
      form: { username: EMAIL, password: PASSWORD },
    })
    expect(response.ok(), `login for the verification client failed: ${response.status()}`)
      .toBeTruthy()
    token = (await response.json()).access_token
    await api.dispose()
  })

  /**
   * NO BROWSER LOGIN HERE (FS-452). Four tests logging in separately, plus the API login
   * above, was five per run against 10/minute — the file passed once and then 429'd,
   * aborting three tests. The suite now authenticates once in a setup project.
   */
  async function login(page: Page) {
    await page.goto('/')
    await expect(page).not.toHaveURL(/\/login/, { timeout: 20_000 })
  }

  async function apiGet(page: Page, path: string) {
    const response = await page.request.get(`${API}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(response.status(), `${path} answered ${response.status()}`).toBeLessThan(400)
    return response.json()
  }

  test('issuing a part creates a shop-floor event with the typed values', async ({ page }) => {
    await login(page)
    await page.goto('/shop-floor')

    const partNumber = `${STAMP}-PART`
    await page.getByLabel('Part number').fill(partNumber)
    await page.getByLabel('Quantity').fill('7')
    await page.getByLabel(/work order/i).first().fill(`${STAMP}-WO`)

    // No network assertion here on purpose: a 200 that wrote nothing is the failure this
    // file exists for, and a 422 that the form swallows is the other one. The artefact is
    // the only thing that settles it.
    await page.getByRole('button', { name: /issue part|submit|record/i }).first().click()
    await page.waitForTimeout(1500)

    const issues = await apiGet(page, '/api/v1/shop-floor/part-issues?limit=50')
    const rows = Array.isArray(issues) ? issues : (issues.items ?? [])
    const mine = rows.filter((e: Record<string, unknown>) =>
      JSON.stringify(e).includes(partNumber),
    )
    expect(
      mine.length,
      `no shop-floor event carries ${partNumber}. The form submitted and the page showed ` +
        `no error, which is exactly what FS-420 looked like — the payload the UI assembles ` +
        `is not the payload the endpoint accepts`,
    ).toBeGreaterThan(0)

    // The QUANTITY matters as much as the row: a write that lands with the wrong values is
    // a different defect from one that does not land, and both present as "it worked".
    expect(
      JSON.stringify(mine[0]),
      `the event exists but does not carry the quantity typed into the form`,
    ).toMatch(/\b7\b/)
  })

  test('clocking in is visible to a second reader', async ({ page }) => {
    await login(page)
    await page.goto('/shop-floor')

    // SCOPED TO THE CARD, and idempotent (FS-451). Two things bit here:
    //
    //   * `getByLabel(/work order/i).last()` matched the input on the "Issue a part" card,
    //     because the "Clock time" card SWAPS ENTIRELY — clocked in it shows only a
    //     "Clock out" button with no work-order field at all;
    //   * an open labor entry survives between runs, and `controls-do-not-break` clicks
    //     Clock In as a side effect, so this arrived to find the operator already clocked
    //     in. A write test that only works on a pristine database is one that passes once.
    // TWO FIXES, and the second undid the first for a while (FS-451).
    //
    // The original failure was the CLICK, not the field: an open labor entry survives
    // between runs — `controls-do-not-break` clicks Clock In as a side effect — so this
    // arrived to find the card swapped to "Clock out" and no Clock in button at all. A
    // write test that only works on a pristine database passes exactly once.
    //
    // Chasing that, I then rewrote the FIELD locator three times (container by heading,
    // container by contained button, preceding-sibling XPath) — all of which resolved to a
    // real element and none of which could see the input. The original `.last()` was
    // correct: `Field` renders the input inside a `<label>`, and exactly two carry the
    // label "Work order (optional)" — Issue a part, then Clock time.
    //
    // Reading the DOM took thirty seconds and would have saved all three attempts.
    // WAIT FOR THE CARD TO SETTLE BEFORE READING ITS STATE. `isVisible()` immediately
    // after `goto` answers about a card that has not rendered yet: the labor query is still
    // in flight, neither button exists, the clock-out branch is skipped as "not clocked
    // in", and then the card renders "Clock out" and the Clock in click finds nothing.
    // Asking a question before the answer exists returns "no", which is a different thing
    // from the answer being no.
    await expect(
      page.getByRole('button', { name: /clock in|clock out/i }).first(),
    ).toBeVisible({ timeout: 20_000 })

    const clockOut = page.getByRole('button', { name: /clock out/i })
    if (await clockOut.isVisible().catch(() => false)) {
      await clockOut.click()
      await expect(page.getByRole('button', { name: /clock in/i })).toBeVisible({
        timeout: 15_000,
      })
    }

    const reference = `${STAMP}-SHIFT`
    await page.getByLabel(/work order/i).last().fill(reference)
    await page.getByRole('button', { name: /clock in/i }).click()
    await expect(page.getByRole('button', { name: /clock out/i })).toBeVisible({
      timeout: 15_000,
    })

    const open = await apiGet(page, '/api/v1/shop-floor/labor/open')
    expect(
      open,
      `clocking in left no open labor entry. The button reported nothing either way, ` +
        `which is the shape of a write that never happened`,
    ).toBeTruthy()
    expect(
      JSON.stringify(open),
      `an open labor entry exists but does not carry ${reference}, so the reference the ` +
        `operator typed did not reach the row`,
    ).toContain(reference)
  })

  test('issuing a part reaches the posting ledger', async ({ page }) => {
    // THE FAN-OUT, not just the row. A part issue is supposed to raise obligations against
    // inventory, purchasing and accounting; a `part_issues` row with an empty ledger is a
    // write that landed and did nothing, which is the harder failure to see — the screen
    // that shows the ledger simply stays empty and looks like a quiet day.
    await login(page)
    await page.goto('/shop-floor')

    const partNumber = `${STAMP}-LEDGER`
    await page.getByLabel('Part number').fill(partNumber)
    await page.getByLabel('Quantity').fill('2')
    await page.getByRole('button', { name: /issue part|submit|record/i }).first().click()
    await page.waitForTimeout(2000)

    const postings = await apiGet(page, '/api/v1/shop-floor/postings?limit=50')
    const rows = Array.isArray(postings) ? postings : (postings.items ?? [])
    expect(
      rows.length,
      'the posting ledger is empty after a part issue. The row may exist while nothing ' +
        'was raised against inventory, purchasing or accounting — and an empty ledger ' +
        'looks exactly like a quiet day',
    ).toBeGreaterThan(0)
  })

  test('the submit button refuses an empty form rather than sending it', async ({ page }) => {
    // FOUND BY THIS TEST FAILING. It originally submitted an invalid form and asserted the
    // refusal reached the screen — and the button turned out to be DISABLED without a part
    // number, so the server never sees it. That is the better design, and worth pinning:
    // a form that submits an invalid payload and swallows the 4xx is indistinguishable
    // from one that succeeded, which is how FS-420 survived for months.
    await login(page)
    await page.goto('/shop-floor')

    await page.getByLabel('Quantity').fill('3')
    const submit = page.getByRole('button', { name: /issue part|submit|record/i }).first()
    await expect(
      submit,
      'the submit button is enabled with no part number, so an invalid payload can reach ' +
        'the server — and whether the operator learns of the refusal is then untested',
    ).toBeDisabled()
  })
})
