import { defineConfig, devices } from '@playwright/test';

/**
 * The same browser, pointed at the BUILT bundle instead of the dev server (FS-766).
 *
 * `playwright.config.ts` runs `npm run dev`, and Vite's dev server does no manual chunking —
 * it serves modules one by one. The chunk graph therefore exists only in `dist/`, and a cycle
 * between two manual chunks white-screened the whole application while every test passed,
 * because nothing had ever loaded the artifact that ships.
 *
 * Deliberately a SEPARATE config rather than a flag on the main one. The dev-server suite is
 * fast and is what people run while working; a build costs ten seconds and belongs in CI and
 * in pre-release checks. Making the everyday suite slower is how a check gets skipped.
 *
 * No auth: this asks whether the bundle can execute, and the login screen executes as much
 * JavaScript as anything behind it.
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: /the-built-bundle-boots\.spec\.ts/,
  timeout: 30_000,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
  },
  webServer: {
    // `vite build` then serve `dist/` — the artifact the Docker image copies into nginx.
    command: 'npx vite build && npx vite preview --port 4173 --strictPort',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
