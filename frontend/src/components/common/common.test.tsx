/**
 * The four small `common/` components (FS-652).
 *
 * All five components in this directory were replaced by `() => null` in every page test
 * that mounts them, so not one had ever been rendered. They reported as covered because a
 * stub and an exercised component look identical to a coverage tool.
 *
 * These are small, and the assertions are correspondingly narrow — but each pins something
 * that has a wrong answer: a badge that renders an empty string for a missing severity, an
 * indicator whose label can be overridden, and a relative time whose `title` is the only
 * place the absolute timestamp appears.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SeverityBadge } from './SeverityBadge'
import { PackMLBadge, PackMLIndicator } from './PackMLBadge'
import { StatusIndicator } from './StatusIndicator'
import { TimeAgo } from './TimeAgo'

describe('SeverityBadge', () => {
  it('capitalises the severity', () => {
    render(<SeverityBadge severity="critical" />)
    expect(screen.getByText('Critical')).toBeInTheDocument()
  })

  it('renders nothing rather than crashing on a missing severity', () => {
    // The component guards with `severity ? … : ''`, which is worth pinning: alarms arrive
    // from a wire that has sent nulls before, and a badge that throws takes the whole row
    // with it. Empty is the right answer here; a crash is not.
    render(<SeverityBadge severity={undefined as never} />)
    expect(document.body.textContent).toBe('')
  })
})

describe('PackMLBadge', () => {
  it('shows the state verbatim, because PackML state names are the vocabulary', () => {
    // Not title-cased or prettified: "Execute" and "Suspended" are ISA-88 terms an
    // operator reads on the machine's own HMI. Rewriting them makes two vocabularies.
    render(<PackMLBadge state="Execute" />)
    expect(screen.getByText('Execute')).toBeInTheDocument()
  })

  it('renders the indicator without a label unless asked', () => {
    const { container } = render(<PackMLIndicator state="Idle" />)
    expect(screen.queryByText('Idle')).not.toBeInTheDocument()
    expect(container.querySelector('span')).toBeTruthy()
  })

  it('shows the label when asked', () => {
    render(<PackMLIndicator state="Idle" showLabel />)
    expect(screen.getByText('Idle')).toBeInTheDocument()
  })
})

describe('StatusIndicator', () => {
  it('labels each status from its own config', () => {
    render(<StatusIndicator status="maintenance" />)
    expect(screen.getByText('Maintenance')).toBeInTheDocument()
  })

  it('lets the caller override the label', () => {
    // The override exists so a caller can say "Offline for 3 days" where the generic
    // "Offline" would understate it. If the override were ignored the caller would have
    // no way to tell — the component still renders something plausible.
    render(<StatusIndicator status="offline" label="Offline since Tuesday" />)
    expect(screen.getByText('Offline since Tuesday')).toBeInTheDocument()
    expect(screen.queryByText('Offline')).not.toBeInTheDocument()
  })

  it('can hide the label entirely', () => {
    render(<StatusIndicator status="online" showLabel={false} />)
    expect(screen.queryByText('Online')).not.toBeInTheDocument()
  })
})

describe('TimeAgo', () => {
  it('carries the absolute timestamp in the title', () => {
    // THE ONLY PLACE IT APPEARS. The visible text is relative — "2 hours ago" — so the
    // title attribute is how anyone recovers when something happened. Dropping it turns
    // every timestamp in the product into an approximation with no way back.
    const when = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString()
    const { container } = render(<TimeAgo date={when} />)
    const span = container.querySelector('span')
    expect(span?.getAttribute('title')).toBe(new Date(when).toLocaleString())
    expect(span?.textContent).not.toBe('')
  })
})
