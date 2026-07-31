import { chromium } from '@playwright/test'

/**
 * Renders the Compliance Assistant against the mock API and captures the page.
 *
 * Not part of the e2e suite — a throwaway harness for eyeballing the page without
 * a live RAG stack. Run with:
 *
 *   VITE_USE_MOCK=true npm run dev &
 *   npx tsx e2e/compliance-assistant.visual.ts
 */
const BASE = process.env.BASE_URL ?? 'http://localhost:9999'
const OUT = process.env.OUT_DIR ?? '/tmp/compliance-shots'

const AUTH = {
  state: {
    user: {
      id: 'u-1',
      email: 'demo@omniusgrid.test',
      name: 'Demo Operator',
      role: 'admin',
      organizationId: 'demo-org',
    },
    accessToken: 'dev-token',
    refreshToken: 'dev-refresh',
    isAuthenticated: true,
  },
  version: 0,
}

async function main() {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })

  const errors: string[] = []
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))

  await page.goto(BASE)
  await page.evaluate((auth) => {
    localStorage.setItem('auth-storage', JSON.stringify(auth))
  }, AUTH)

  await page.goto(`${BASE}/compliance`)
  await page.waitForLoadState('networkidle')

  const navItem = await page.getByRole('link', { name: /Compliance Assistant/i }).count()
  console.log(`sidebar nav item present: ${navItem > 0}`)
  console.log(`idle state rendered: ${await page.getByText(/Ask a question about policy/i).count() > 0}`)
  await page.screenshot({ path: `${OUT}/01-idle.png`, fullPage: true })

  // Ask via a suggestion chip, which is also the shortest path to a full answer.
  await page.getByText('What PPE does our lockout/tagout procedure require?').click()
  await page.getByText('Cited passages').waitFor({ timeout: 15_000 })
  await page.screenshot({ path: `${OUT}/02-answer.png`, fullPage: true })

  const checks: Record<string, number> = {
    answerPanel: await page.getByText('Answer', { exact: true }).count(),
    citedPassages: await page.getByText('Cited passages').count(),
    formsPanel: await page.getByText('Forms you may need').count(),
    sourcesPanel: await page.getByText('Source documents').count(),
    alsoRelevant: await page.getByText('Also relevant').count(),
    openButtons: await page.getByRole('button', { name: /^Open$/ }).count(),
    formBadge: await page.getByText('Form', { exact: true }).count(),
  }
  console.log(JSON.stringify(checks, null, 2))

  // The operational (ERP) block must not be visible anywhere on the page.
  const body = (await page.textContent('body')) ?? ''
  console.log(`operational block leaked into the DOM: ${/Operational records|WorkOrder \|/.test(body)}`)

  console.log(errors.length ? `console errors:\n${errors.join('\n')}` : 'no console errors')
  await browser.close()
}

main()
