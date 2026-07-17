// Type declarations for jest-axe, which ships no types. We intentionally do
// not use @types/jest-axe: it pulls in @types/jest, whose globals conflict
// with vitest. Only the surface this codebase uses is declared.
declare module 'jest-axe' {
  import type { AxeResults, RunOptions, Spec } from 'axe-core';

  export interface JestAxeConfigureOptions extends RunOptions {
    globalOptions?: Spec;
  }

  export type JestAxe = (
    html: Element | string,
    options?: RunOptions
  ) => Promise<AxeResults>;

  export const axe: JestAxe;
  export function configureAxe(options?: JestAxeConfigureOptions): JestAxe;

  export interface AxeMatcherResult {
    pass: boolean;
    actual: AxeResults['violations'];
    message(): string;
  }

  export const toHaveNoViolations: {
    toHaveNoViolations(results: AxeResults): AxeMatcherResult;
  };
}

// The matcher is registered on vitest's expect in src/test/setup.ts; the
// Assertion augmentation lives in vitest-matchers.d.ts (it must be a module
// file to merge with vitest's types, while this one must stay a script so
// the untyped 'jest-axe' module can be declared).
