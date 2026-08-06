import { test, expect, Page } from '@playwright/test'
import { ROUTES } from './routes'

/**
 * With every API call failing, no page may claim the world is empty (FS-489).
 *
 * `failureIsNotEmptiness.test.ts` sweeps the source for this class three ways — an
 * empty-state phrase with no error branch guarding it, a widget gated on an unguarded query,
 * and a query that models loading but not failure. All three read one file at a time.
 *
 * **A page is not one file.** It composes a dozen panels, each with its own query, and the
 * question an operator actually faces is what the whole screen says when the backend is
 * unreachable. "No trailers found" is a claim about the yard. "No production errors
 * recorded" is a claim about the week. Rendered while every request is failing, they are
 * lies — and no per-file sweep can see a page that is individually correct in every part and
 * collectively wrong.
 *
 * NEEDS NO BACKEND, which is the point. Auth is seeded into localStorage and every
 * `/api/**` request is failed at the network layer, so this runs in the fast browser job
 * beside the smoke tests rather than the one that stands up Postgres. Failing the requests
 * outright is also a harsher test than a live backend returning empty sets: there is no
 * ambiguity about whether the data is genuinely absent.
 *
 * WHAT IT ASSERTS, and the two directions. A route must not render an empty-state phrase
 * while everything is failing; and it must render SOMETHING that admits the failure, because
 * a blank page is its own defect — the operator learns nothing either way.
 */

const AUTH = {
  state: {
    user: {
      id: 'e2e-user',
      email: 'e2e@omniusgrid.test',
      name: 'E2E Operator',
      role: 'admin',
      organizationId: 'e2e-org',
    },
    accessToken: 'e2e-token',
    refreshToken: 'e2e-refresh',
    isAuthenticated: true,
  },
  version: 0,
}

/**
 * The phrases that assert something about the WORLD rather than about the request.
 *
 * Deliberately narrower than the source sweep's regex. That one reads static JSX and can
 * afford to be broad; this one reads rendered text, where a false positive is a red build
 * nobody can act on. Each of these is a sentence a page shows in place of data.
 */
const EMPTINESS_CLAIMS = [
  /\bno (?:trailers|assets|alarms|releases|rollouts|errors|deliveries|items|results|data points|geofence alerts|agent heartbeats|commands)\b/i,
  /\bnot found\b/i,
  /\bnone yet\b/i,
  /\bnothing (?:to do|outstanding|scheduled)\b/i,
  /\bno production errors recorded\b/i,
]

/**
 * Text that shows the page knows something went wrong. Matched loosely on purpose: the
 * wording differs per page by design — each says what did not happen in its own terms — and
 * pinning the prose would make this a spelling test.
 */
const ADMITS_FAILURE =
  /\b(?:failed|failure|could ?n[o']t|could not|unavailable|unreachable|error|try again|retry|not loaded|cannot)\b/i

async function seedAuth(page: Page) {
  await page.goto('/')
  await page.evaluate((auth) => {
    localStorage.setItem('auth-storage', JSON.stringify(auth))
  }, AUTH)
}

/** Fail every backend call at the network layer — no backend involved, no ambiguity.
 *
 *  THE PATTERN IS `/api/v1/`, NOT `/api/`. The frontend's own source lives in `src/api/`,
 *  and the Vite dev server serves those modules over HTTP — so `**` + `/api/` + `**` also
 *  matches `/src/api/client.ts` and aborts the application's own JavaScript. React then
 *  never mounts, the body is empty, and **every assertion below passes**: a page that
 *  rendered nothing claims no emptiness. The first version of this file did exactly that
 *  and reported 32 green tests while testing a blank document.
 *
 *  `assertTheAppRendered` exists so that cannot happen quietly again. */
async function breakTheApi(page: Page) {
  await page.route('**/api/v1/**', (route) => route.abort('failed'))
}

/** The page must have rendered SOMETHING before any claim about its text means anything. */
async function assertTheAppRendered(page: Page, route: string) {
  const body = (await page.locator('body').innerText()).replace(/\s+/g, ' ').trim()
  expect(
    body.length,
    `${route} rendered an empty document, so every assertion about its text is vacuous — ` +
      `the app did not mount. Check that the route interception is not also blocking the ` +
      `dev server's own modules.`,
  ).toBeGreaterThan(20)
  return body
}

test.describe('a failing backend is not an empty world', () => {
  for (const route of ROUTES) {
    test(`${route} does not claim emptiness while every request is failing`, async ({ page }) => {
      await seedAuth(page)
      await breakTheApi(page)
      await page.goto(route)

      // Let the queries reject and the error branches render. `networkidle` is unreliable
      // with polling components, so this waits on the page settling instead.
      await page.waitForLoadState('domcontentloaded')
      await page.waitForTimeout(1500)

      const body = await assertTheAppRendered(page, route)

      // Report the MATCH IN CONTEXT, not the first 400 characters of the page — every
      // route here starts with the same nav sidebar, so a leading slice tells the reader
      // nothing about which sentence failed or where it came from.
      const claimed = EMPTINESS_CLAIMS.flatMap((pattern) => {
        const hit = body.match(pattern)
        if (!hit || hit.index === undefined) return []
        return [`"${body.slice(Math.max(0, hit.index - 60), hit.index + 120).trim()}"`]
      })
      expect(
        claimed,
        `${route} tells the operator something is empty while every API call is failing. ` +
          `An empty yard, a clear alarm list and a quiet week are claims about the world, ` +
          `and this page has no idea.`,
      ).toEqual([])
    })
  }
})

test.describe('and it does not go blank instead', () => {
  // The other direction, on a sample rather than every route: a page that renders nothing at
  // all passes the check above and tells the operator just as little. Three routes whose
  // whole content is server data, so there is no static shell to hide behind.
  for (const route of ['/assets', '/alarms', '/logistics/yard']) {
    test(`${route} says something went wrong`, async ({ page }) => {
      await seedAuth(page)
      await breakTheApi(page)
      await page.goto(route)
      await page.waitForLoadState('domcontentloaded')
      await page.waitForTimeout(1500)

      const body = await assertTheAppRendered(page, route)

      expect(
        ADMITS_FAILURE.test(body),
        `${route} renders no acknowledgement that anything failed. A blank page and a ` +
          `working one look the same to somebody deciding whether to act. Rendered text: ` +
          `${body.slice(0, 400)}`,
      ).toBe(true)
    })
  }
})
