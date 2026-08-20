import { expect, test } from '@playwright/test';

/**
 * The production bundle actually renders (FS-766).
 *
 * THIS WAS BROKEN AND NOTHING NOTICED. `vite.config.ts` split React into its own manual
 * chunk, which produced a cycle between two chunks:
 *
 *     react-vendor.js  imports -> vendor.js
 *     vendor.js        imports -> react-vendor.js
 *
 * ES modules resolve a cycle by handing out partially-initialised bindings, so whichever
 * evaluated first saw `undefined` for the other's exports. `vendor` won, reached
 * `React.createContext` inside react-query, and threw. **The entire application was a white
 * screen in any production build** — while `vite build` exited 0, `tsc` was clean, and 1,211
 * unit tests passed.
 *
 * WHY EVERY EXISTING TEST MISSED IT. `playwright.config.ts` runs `webServer.command:
 * 'npm run dev'`. The dev server does no manual chunking at all — it serves modules
 * individually — so the chunk graph that broke exists **only** in the artifact that ships,
 * and no test had ever loaded that artifact. Unit tests import source. The e2e suite drove
 * the dev server. The Docker image build was verified by checking nginx returned 200 for
 * `index.html`, which it did: a 200 for a page that then throws on load.
 *
 * That is the whole lesson, and it is why this file runs against `vite preview` rather than
 * `npm run dev`: **the artifact under test has to be the artifact that ships.**
 *
 * The assertions are deliberately shallow. This is not about features — the rest of the
 * suite covers those. It is about whether the bundle can execute at all, which is a question
 * nobody was asking.
 */
test.describe('the production bundle', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('executes without throwing on load', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));

    await page.goto('/', { waitUntil: 'load' });
    await page.waitForTimeout(1500);

    expect(
      errors,
      `the built bundle threw while loading:\n${errors.join('\n')}\n\n` +
        'A module-evaluation error here is usually a manual-chunk cycle in vite.config.ts. ' +
        'It cannot reproduce on the dev server, which does not chunk.'
    ).toEqual([]);
  });

  test('renders something into the root element', async ({ page }) => {
    // The failure mode was a white screen with a populated <div id="root"> in the HTML and
    // nothing mounted into it, so asserting the response was 200 — which the Docker image
    // check did — proves nothing at all.
    await page.goto('/', { waitUntil: 'load' });
    await expect(page.locator('#root')).not.toBeEmpty({ timeout: 10_000 });
  });

  test('mounts React rather than only shipping markup', async ({ page }) => {
    await page.goto('/', { waitUntil: 'load' });
    // Any interactive control means the tree hydrated and event handlers are attached; a
    // static shell would satisfy the assertion above and still be a dead application.
    await expect(
      page.locator('button, a[href], input').first()
    ).toBeVisible({ timeout: 10_000 });
  });
});
