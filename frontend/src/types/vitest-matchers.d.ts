// Augments vitest's expect() assertions with the jest-axe matcher registered
// in src/test/setup.ts. Kept separate from jest-axe.d.ts: module augmentation
// only merges (rather than replaces) when the file itself is a module.
import 'vitest';

declare module 'vitest' {
  interface Assertion<T = any> {
    toHaveNoViolations(): T;
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void;
  }
}
