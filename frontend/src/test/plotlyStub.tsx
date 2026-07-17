// Test stub for react-plotly.js: plotly requires canvas/WebGL at import time,
// which jsdom lacks. Aliased in vitest.config.ts only (real builds use plotly).
import { FC } from 'react'

const Plot: FC<Record<string, unknown>> = () => <div data-testid="plotly-stub" />
export default Plot
