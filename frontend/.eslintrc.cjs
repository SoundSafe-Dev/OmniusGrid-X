/* ESLint config (FS-54) — the standard Vite react-ts template shape for the
 * toolchain already pinned in package.json (eslint 8 + @typescript-eslint 6 +
 * react-hooks + react-refresh). `npm run lint` had no config at all before
 * this file, so it exited 2 without linting anything.
 */
module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: [
    'dist',
    'out',
    'node_modules',
    'coverage',
    '.eslintrc.cjs',
    'video', // Remotion compositions — separate toolchain, linted on their own terms
  ],
  parser: '@typescript-eslint/parser',
  plugins: ['react-refresh'],
  rules: {
    // HMR-only concern (16 pre-existing hits, several in files that
    // intentionally co-export hooks/constants with components). Off rather
    // than blocking; worst case a dev-server edit falls back to full reload.
    'react-refresh/only-export-components': 'off',
    // The codebase predates the config; these two rules carry hundreds of
    // pre-existing hits that are stylistic, not correctness. Keep them off
    // rather than drowning real signals; tighten in a dedicated pass.
    '@typescript-eslint/no-explicit-any': 'off',
    '@typescript-eslint/no-non-null-assertion': 'off',
    // Underscore prefix is the codebase's deliberate-ignore convention.
    '@typescript-eslint/no-unused-vars': [
      'error',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
  },
};
