// Augment vitest's expect with the jest-axe matcher registered in
// src/test/setup.ts via expect.extend(toHaveNoViolations). The import makes
// this file a module so the declaration below merges instead of shadowing.
import 'vitest';

declare module 'vitest' {
  // The type parameter list must match vitest's own Assertion declaration for
  // interface merging, including its `any` default.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  interface Assertion<T = any> {
    toHaveNoViolations(): T;
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void;
  }
}
