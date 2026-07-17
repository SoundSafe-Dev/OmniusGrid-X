import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AnnotatedChart } from './AnnotatedChart'

const TRACES = [
  { type: 'scatter', name: 'OEE (%)', x: ['Current'], y: [78] },
  { type: 'scatter', name: 'Availability (%)', x: ['Current'], y: [91] },
]

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AnnotatedChart', () => {
  it('renders the card title, plot, and export button', () => {
    render(<AnnotatedChart data={TRACES} title="Fleet OEE Trend" />)
    expect(screen.getByText('Fleet OEE Trend')).toBeInTheDocument()
    expect(screen.getByText('Export CSV')).toBeInTheDocument()
    expect(screen.getByTestId('plotly-stub')).toBeInTheDocument()
  })

  it('downloads a CSV of the visible traces on export', () => {
    // jsdom has no createObjectURL / anchor navigation.
    const createUrl = vi.fn((_blob: Blob | MediaSource) => 'blob:fake')
    const revokeUrl = vi.fn()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: revokeUrl }))
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    render(<AnnotatedChart data={TRACES} title="Fleet OEE Trend" />)
    fireEvent.click(screen.getByText('Export CSV'))

    expect(createUrl).toHaveBeenCalledTimes(1)
    const blob = createUrl.mock.calls[0][0] as Blob
    expect(blob.type).toContain('text/csv')
    expect(click).toHaveBeenCalledTimes(1)
    expect(revokeUrl).toHaveBeenCalledWith('blob:fake')
  })
})
