import { vi } from 'vitest'

/**
 * Load an API module in REAL (non-mock) mode (FS-238).
 *
 * WHY THIS IS NEEDED. `src/test/setup.ts` does
 * `vi.stubEnv('VITE_USE_MOCK', 'true')` before any module evaluates, and
 * `src/api/mockMode.ts` reads it into a module-level `const USE_MOCK`. That
 * combination means EVERY unit test has always exercised the mock branch, so the
 * ~200 `if (USE_MOCK)` forks across `src/api/` could drift from the real request
 * shape — wrong path, wrong query parameter, wrong response mapping — and no test
 * would notice. The mock branch is not the code that runs in production.
 *
 * Because `USE_MOCK` is captured at import time, flipping the env inside a test is
 * not enough: the module has already been evaluated with the old value. The module
 * registry has to be reset and the module re-imported, which is what this does.
 *
 * Usage:
 *   const { alarmsApi } = await loadInRealMode(() => import('../api/alarms'))
 *
 * The env stub is restored by `vi.unstubAllEnvs()` in an afterEach, so a real-mode
 * test cannot leak its mode into the next test.
 */
export async function loadInRealMode<T>(importer: () => Promise<T>): Promise<T> {
  vi.stubEnv('VITE_USE_MOCK', 'false')
  // Drop the cached modules so `mockMode` — and every api module that imported it
  // — re-evaluates against the env we just set.
  vi.resetModules()
  return importer()
}

/** Restore mock mode and the module registry. Call from afterEach. */
export function restoreMockMode(): void {
  vi.unstubAllEnvs()
  vi.resetModules()
}
