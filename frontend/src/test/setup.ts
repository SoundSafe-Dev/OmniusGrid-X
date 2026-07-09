// Vitest global setup (task 1).
import '@testing-library/jest-dom/vitest'
import { expect } from 'vitest'
import { toHaveNoViolations } from 'jest-axe'

// Accessibility matcher for the a11y checks (task 6).
expect.extend(toHaveNoViolations)

// jsdom lacks ResizeObserver; recharts' ResponsiveContainer requires it.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver ?? (ResizeObserverStub as any)
