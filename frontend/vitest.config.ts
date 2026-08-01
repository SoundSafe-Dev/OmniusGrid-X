/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Separate from vite.config.ts (prod build) so the test harness is self-contained.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // plotly needs canvas/WebGL at import time, which jsdom lacks — stub the
      // whole react wrapper under test (real builds use the actual library).
      'react-plotly.js': new URL('./src/test/plotlyStub.tsx', import.meta.url).pathname,
      'plotly.js': 'plotly.js-dist-min',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      // WIDENED in FS-240. This used to be three paths — two stores files, one
      // websocket client and one component — which made the reported percentage
      // decorative: it measured the code we happened to have tested, so it could
      // never fall no matter how much untested code was added.
      //
      // The scope below is the code a regression would actually be felt in.
      include: [
        'src/api/**',
        'src/stores/**',
        'src/hooks/**',
        'src/components/ui/**',
        'src/pages/**',
      ],
      exclude: [
        '**/*.test.{ts,tsx}',
        '**/*.spec.{ts,tsx}',
        'src/test/**',
        // Mock datasets are fixtures, not product code; counting them would
        // inflate the number with data that has no behaviour to test.
        'src/api/mockApi.ts',
        'src/api/generated/**',
      ],
      // RAISED 2026-07-31 (FS-260). Set from the MEASURED value, with ~1 point of
      // margin, so this is a ratchet rather than an aspiration: it cannot be met by
      // deleting tests, and it fails if new untested code dilutes the total.
      //
      //   set by FS-240   19.83 / 16.16 / 14.51 / 20.55   -> 19 / 15 / 14 / 19
      //   measured today  39.01 / 42.78 / 35.21 / 40.23   -> 38 / 41 / 34 / 39
      //
      // Coverage had roughly DOUBLED while the thresholds stood still, which made
      // them decorative in the direction nobody checks: the gate would have sat
      // through coverage falling by half and still passed. A ratchet that trails
      // reality by 20 points is not a ratchet, it is a number in a config file.
      //
      // FS-260 was written up as "no thresholds exist, and the coverage `include` is
      // narrowed to three paths". Neither reproduced — FS-240 had already widened the
      // include and set these. The real defect was the opposite one, and the sprint
      // entry has been corrected in place per that document's own instruction.
      //
      // Raise these as coverage improves. Do NOT lower them to make a build pass:
      // the point is that dropping below today's level is a regression.
      thresholds: {
        statements: 38,
        branches: 41,
        functions: 34,
        lines: 39,
      },
    },
  },
})
