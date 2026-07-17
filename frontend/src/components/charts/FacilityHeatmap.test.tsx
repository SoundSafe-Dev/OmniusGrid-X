import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FacilityHeatmap } from './FacilityHeatmap'

// react-plotly.js is aliased to src/test/plotlyStub.tsx (vitest.config.ts):
// plotly needs canvas/WebGL at import time, which jsdom lacks.
describe('FacilityHeatmap', () => {
  it('renders the card title and the plot for grid data', () => {
    render(
      <FacilityHeatmap
        title="OEE by Asset"
        data={[
          { x: 0, y: 0, value: 86, label: 'Printer #1: 86%' },
          { x: 1, y: 0, value: 64, label: 'CNC Mill #1: 64%' },
        ]}
      />
    )
    expect(screen.getByText('OEE by Asset')).toBeInTheDocument()
    expect(screen.getByTestId('plotly-stub')).toBeInTheDocument()
  })
})
