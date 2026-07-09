import { defineConfig, devices } from '@playwright/test'

// E2E smoke config (task 2). Boots the Vite dev server and drives Chromium.
// Browsers are installed in CI via `npx playwright install --with-deps chromium`.
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://localhost:9999',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:9999',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
