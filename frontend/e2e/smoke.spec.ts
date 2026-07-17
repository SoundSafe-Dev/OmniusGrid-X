import { test, expect } from '@playwright/test'

// E2E smoke suite (task 2): the critical path renders without crashing. The app
// runs in mock mode (USE_MOCK) so these pass without a live backend.

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
