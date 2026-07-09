// Vitest global setup (task 1).
import '@testing-library/jest-dom/vitest'
import { expect } from 'vitest'
import { toHaveNoViolations } from 'jest-axe'

// Accessibility matcher for the a11y checks (task 6).
expect.extend(toHaveNoViolations)
