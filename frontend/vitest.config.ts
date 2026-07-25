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
      // Set from the MEASURED value at the time of writing (19.83% statements /
      // 16.16% branches / 14.51% functions / 20.55% lines) with a small margin,
      // so this is a ratchet rather than an aspiration. It cannot be met by
      // deleting tests, and it fails if new untested code dilutes the total.
      //
      // Raise these as coverage improves. Do NOT lower them to make a build pass:
      // the point is that dropping below today's level is a regression.
      thresholds: {
        statements: 19,
        branches: 15,
        functions: 14,
        lines: 19,
      },
    },
  },
})
