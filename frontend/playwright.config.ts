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
  projects: [
    // ONE LOGIN FOR THE WHOLE SUITE (FS-452). `AUTH_LOGIN_RATE_LIMIT` is 10/minute and
    // compose enables rate limiting by default; the suite hit that ceiling twice, three
    // days apart, in two different files — each fixed inside itself, so the second could
    // not benefit from the first. A rate limiter is a shared resource.
    //
    // The setup project runs first and writes the authenticated state to disk; every spec
    // below loads it, so the suite spends exactly one login however many tests it grows to.
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], storageState: 'e2e/.auth/user.json' },
      dependencies: ['setup'],
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:9999',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
