// Ambient typings for 'jest-axe', which ships no type declarations.
// Scoped to what src/test/setup.ts and a11y.test.tsx actually use.
declare module 'jest-axe' {
  import type { AxeResults, RunOptions, Spec } from 'axe-core';

  export interface JestAxeConfigureOptions {
    globalOptions?: Spec;
    rules?: RunOptions['rules'];
  }

  export function axe(
    html: Element | string,
    options?: RunOptions
  ): Promise<AxeResults>;

  export function configureAxe(options?: JestAxeConfigureOptions): typeof axe;

  export const toHaveNoViolations: {
    toHaveNoViolations(results: AxeResults): {
      pass: boolean;
      message(): string;
    };
  };
}
