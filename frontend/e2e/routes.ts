/**
 * Every routed page except `/login`, which has no authenticated content to check.
 *
 * NOT A SPEC, and it lives here rather than inside one because **Playwright refuses to let a
 * spec import another spec** — "test file X should not import test file Y" is a hard error
 * that fails collection for the WHOLE suite, not just the importing file. `ROUTES` was
 * exported from `data-reaches-the-screen.spec.ts` and a second spec imported it; the result
 * was `Total: 0 tests in 0 files`.
 *
 * That failure is only visible when the whole suite is listed. Running the new file alone
 * passed, because the rule triggers when both are collected — so the check that caught it was
 * `npx playwright test --list` with no filter, and nothing else would have.
 *
 * `everyRouteIsSwept.test.ts` reads this list to assert the e2e sweep covers every route in
 * `App.tsx`, so the array shape here is load-bearing for that regex too.
 */
export const ROUTES = [
  '/', '/assets', '/alarms', '/alarms/rules', '/oee', '/kanban', '/shop-floor',
  '/activations', '/engines/tactical', '/engines/strategic', '/engines/mlops',
  '/engines/cloud', '/analytics/telemetry', '/analytics/health', '/analytics/maintenance',
  '/predictive/rul', '/predictive/historian', '/fleet', '/fleet/organization',
  '/logistics/yard', '/logistics/transportation', '/erp', '/compliance', '/nlp', '/intake',
  '/admin/users', '/admin/collectors', '/admin/health', '/admin/settings',
  '/admin/notifications', '/admin/errors', '/admin/fleet', '/admin/export-deliveries',
]
