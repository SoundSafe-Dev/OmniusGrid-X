// Vitest global setup (task 1).
import '@testing-library/jest-dom/vitest'
import { expect, vi } from 'vitest'
import { toHaveNoViolations } from 'jest-axe'

// The app defaults to real API mode (USE_MOCK in src/api/mockMode.ts reads
// VITE_USE_MOCK==='true'). API-client unit tests run offline against the
// in-browser mock dataset, so force mock mode before any api module evaluates.
vi.stubEnv('VITE_USE_MOCK', 'true')

// Accessibility matcher for the a11y checks (task 6).
expect.extend(toHaveNoViolations)

// jsdom lacks ResizeObserver; recharts' ResponsiveContainer requires it.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver ?? (ResizeObserverStub as any)
