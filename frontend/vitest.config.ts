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
      // Seed coverage on the non-feature core we test here; expand over time.
      include: ['src/stores/**', 'src/api/websocket.ts', 'src/components/ErrorBoundary.tsx'],
    },
  },
})
