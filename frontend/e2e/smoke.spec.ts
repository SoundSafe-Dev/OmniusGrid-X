import { test, expect } from '@playwright/test'

// E2E smoke suite (task 2): the critical path renders without crashing.
//
// NOTE: the app does NOT run in mock mode here — this comment used to claim it
// did. `npm run dev` sets no VITE_USE_MOCK and src/api/mockMode.ts defaults it
// OFF, so Playwright has always driven the REAL API client. These tests pass
// without a backend only because they assert unauthenticated rendering and a
// redirect, neither of which needs one. The authenticated journey that does need
// a backend lives in authenticated.spec.ts.

test('login page renders', async ({ page }) => {
  await page.goto('/login')
  await expect(page).toHaveTitle(/Omnius|OpsGrid|Grid/i)
  // A login form control is present.
  await expect(page.locator('input').first()).toBeVisible()
})

test('unknown route shows 404', async ({ page }) => {
  await page.goto('/this-route-does-not-exist')
  await expect(page.getByText('404')).toBeVisible()
})

test('protected route redirects to login when unauthenticated', async ({ page }) => {
  await page.context().clearCookies()
  await page.goto('/assets')
  // ProtectedRoute bounces unauthenticated users to /login.
  await expect(page).toHaveURL(/\/login/)
})
