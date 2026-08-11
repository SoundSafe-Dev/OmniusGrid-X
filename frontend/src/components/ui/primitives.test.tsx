/**
 * The five `ui/` primitives that had no test of their own (FS-652b).
 *
 * All five reported high line coverage because pages that render them are tested — which is
 * the same mistake `ui/Select.tsx` made at 100%: coverage counts a line that executed, not a
 * behaviour anybody asserted. What is pinned here is the branch each one owns: `Card`'s
 * conditional header, `ChartContainer`'s loading/error/content precedence, `Skeleton`'s
 * shape, `Tooltip`'s content wiring and `Wordmark`'s split weight.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Card } from './Card'
import { ChartContainer } from './ChartContainer'
import { Skeleton, SkeletonCard, SkeletonTable } from './Skeleton'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './Tooltip'
import { Wordmark } from './Wordmark'

describe('Card', () => {
  it('renders its children with no header when given no header props', () => {
    const { container } = render(<Card>body</Card>)
    expect(screen.getByText('body')).toBeInTheDocument()
    // The whole header block is behind `(title || subtitle || action)` — an empty bordered
    // strip above every card would be visible on every page that uses one.
    expect(container.querySelector('.border-b')).toBeNull()
  })

  it('renders the header when only a subtitle is given', () => {
    // `subtitle` alone has to open the header; a card titled by its subtitle is a real usage
    // and the condition is an OR, not a check on `title`.
    render(<Card subtitle="Line 3">body</Card>)
    expect(screen.getByText('Line 3')).toBeInTheDocument()
  })

  it('puts the title in a heading, not a styled div', () => {
    render(<Card title="Throughput">body</Card>)
    expect(screen.getByRole('heading', { name: 'Throughput' })).toBeInTheDocument()
  })

  it('renders the action node beside the title', () => {
    render(
      <Card title="Throughput" action={<button type="button">Export</button>}>
        body
      </Card>,
    )
    expect(screen.getByRole('button', { name: 'Export' })).toBeInTheDocument()
  })

  it('drops the inner padding when asked, and keeps the children', () => {
    const { container } = render(<Card noPadding>body</Card>)
    expect(container.querySelector('.p-4')).toBeNull()
    expect(screen.getByText('body')).toBeInTheDocument()
  })

  it('forwards its ref and its extra DOM props', () => {
    // It is a `forwardRef` over a spread of `HTMLAttributes`; both are the reason callers
    // can attach a click handler or measure it, and neither is exercised by rendering alone.
    let node: HTMLDivElement | null = null
    render(
      <Card ref={(el) => { node = el }} data-testid="card">
        body
      </Card>,
    )
    expect(node).toBeInstanceOf(HTMLDivElement)
    expect(screen.getByTestId('card')).toBeInTheDocument()
  })
})

describe('ChartContainer', () => {
  it('shows the chart when there is neither a load nor an error', () => {
    render(<ChartContainer title="OEE"><svg data-testid="chart" /></ChartContainer>)
    expect(screen.getByTestId('chart')).toBeInTheDocument()
  })

  it('hides the chart while loading', () => {
    // A chart rendered under a spinner is a chart drawn from stale or empty data, which is
    // the failure this component exists to prevent.
    render(<ChartContainer loading><svg data-testid="chart" /></ChartContainer>)
    expect(screen.queryByTestId('chart')).toBeNull()
  })

  it('shows the error instead of the chart', () => {
    render(
      <ChartContainer error="Telemetry unavailable"><svg data-testid="chart" /></ChartContainer>,
    )
    expect(screen.getByText('Telemetry unavailable')).toBeInTheDocument()
    expect(screen.queryByTestId('chart')).toBeNull()
  })

  it('announces the error, rather than only colouring it', () => {
    // The same gap `ui/Select.tsx` had: error text with no role reaches a sighted user and
    // nobody else. A chart that failed to load is exactly when a screen reader user has no
    // other cue at all.
    render(<ChartContainer error="Telemetry unavailable">x</ChartContainer>)
    expect(screen.getByRole('alert')).toHaveTextContent('Telemetry unavailable')
  })

  it('prefers loading over an error when both are set', () => {
    // A refetch after a failure sets both; showing the stale error over a live load would
    // tell the operator the retry had already failed.
    render(<ChartContainer loading error="Telemetry unavailable">x</ChartContainer>)
    expect(screen.queryByText('Telemetry unavailable')).toBeNull()
  })

  it('applies the height it was given', () => {
    const { container } = render(<ChartContainer height={420}>x</ChartContainer>)
    expect(container.querySelector('[style*="420"]')).not.toBeNull()
  })
})

describe('Skeleton', () => {
  it('takes the width and height it is given', () => {
    const { container } = render(<Skeleton width="60%" height={24} />)
    const el = container.firstElementChild as HTMLElement
    expect(el.style.width).toBe('60%')
    expect(el.style.height).toBe('24px')
  })

  it('is a rectangle by default and a circle on request', () => {
    const { container: square } = render(<Skeleton />)
    const { container: round } = render(<Skeleton circle />)
    expect(square.firstElementChild).toHaveClass('rounded')
    expect(round.firstElementChild).toHaveClass('rounded-full')
  })

  it('draws a card of the requested line count, plus its heading bar', () => {
    const { container } = render(<SkeletonCard lines={5} />)
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(6)
  })

  it('draws rows × columns cells, plus a header row', () => {
    // 3 columns of header + 2 rows × 3 columns. The nested `Array.from` pair is the only
    // real logic in the file and an off-by-one here shows as a table missing a column.
    const { container } = render(<SkeletonTable rows={2} columns={3} />)
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(9)
  })
})

describe('Tooltip', () => {
  it('renders its trigger, and the content only once opened', () => {
    render(
      <TooltipProvider>
        <Tooltip open>
          <TooltipTrigger>What is OEE?</TooltipTrigger>
          <TooltipContent>Availability × Performance × Quality</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    )
    expect(screen.getByText('What is OEE?')).toBeInTheDocument()
    expect(screen.getAllByText('Availability × Performance × Quality').length).toBeGreaterThan(0)
  })

  it('keeps the content out of the tree while closed', () => {
    render(
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger>What is OEE?</TooltipTrigger>
          <TooltipContent>Availability × Performance × Quality</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    )
    expect(screen.queryByText('Availability × Performance × Quality')).toBeNull()
  })
})

describe('Wordmark', () => {
  it('renders the two halves as one word', () => {
    const { container } = render(<Wordmark />)
    expect(container.textContent).toBe('OmniusGrid')
  })

  it('keeps the split weight the brand asks for', () => {
    // BRAND.md: "Omnius" extrabold, "Grid" regular. Collapsing them to one span is the
    // easy edit and it silently loses the mark.
    const { container } = render(<Wordmark />)
    expect(container.querySelector('.font-extrabold')).toHaveTextContent('Omnius')
    expect(container.querySelector('.font-normal')).toHaveTextContent('Grid')
  })

  it('passes a caller class through to the outer span', () => {
    const { container } = render(<Wordmark className="text-2xl" />)
    expect(container.firstElementChild).toHaveClass('text-2xl')
  })
})
