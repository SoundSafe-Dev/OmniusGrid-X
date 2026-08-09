import { test as setup, expect } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { dirname } from 'node:path'

/**
 * One login for the whole suite (FS-452).
 *
 * `AUTH_LOGIN_RATE_LIMIT` is `10/minute` and compose turns rate limiting ON by default. The
 * suite reached that ceiling twice, three days apart, in two different files:
 *
 *   FS-447  twelve logins in `data-reaches-the-screen.spec.ts` — two tests failed on a login
 *           TIMEOUT rather than on anything they assert, and which two depended on worker
 *           scheduling
 *   FS-451  five logins in `writes-actually-persist.spec.ts` — the file passed once and then
 *           returned **429** on the second run in a minute, aborting three tests before they
 *           started
 *
 * Both were fixed the same way, in the same shape, inside the file that hit it. **A rate
 * limiter is a shared resource, and a per-file remedy is a per-file remedy** — the second
 * file could not benefit from the first file's fix, and a third would have hit it again.
 *
 * This is the shared one. Playwright runs a `setup` project before everything else, saves
 * the authenticated state to disk, and every spec loads it — so the whole suite spends
 * exactly ONE login no matter how many files or tests it grows to.
 *
 * It also removes a per-test cost: logging in is a form fill, a round trip and a
 * navigation, repeated 48 times.
 */

export const STATE_PATH = 'e2e/.auth/user.json'

const EMAIL = process.env.E2E_USER_EMAIL ?? 'e2e@omniusgrid.test'
const PASSWORD = process.env.E2E_USER_PASSWORD ?? 'e2e-playwright-password'

setup('authenticate once for the whole suite', async ({ page }) => {
  setup.skip(
    process.env.E2E_LIVE_BACKEND !== '1',
    'no live backend; the specs that need this state skip too',
  )

  mkdirSync(dirname(STATE_PATH), { recursive: true })

  await page.goto('/login')
  await page.getByLabel(/username/i).fill(EMAIL)
  await page.getByLabel(/password/i).fill(PASSWORD)
  await page.getByRole('button', { name: /sign in|log ?in/i }).click()

  // Landing anywhere other than /login means the token round-trip worked. Asserted here so
  // a broken login fails ONCE with a clear message, rather than as 48 confusing timeouts.
  await expect(page).not.toHaveURL(/\/login/, { timeout: 20_000 })

  await page.context().storageState({ path: STATE_PATH })
})
