import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { YardMapPanel, groupTrailersByZone } from './YardMapPanel'

const trailer = (over: Record<string, any>): any => ({
  id: over.id ?? 't1', trailerId: over.trailerId ?? 'TRL-1', carrierName: 'ACME',
  trailerType: 'dry_van', status: 'yard', detentionRisk: 'low', detentionCost: 0,
  ...over,
})

const door = (over: Record<string, any>): any => ({
  id: over.id ?? 'd1', doorNumber: over.doorNumber ?? '1', status: over.status ?? 'available',
})

describe('groupTrailersByZone', () => {
  it('groups in-yard trailers by location, skipping transit/outbound/docked', () => {
    const zones = groupTrailersByZone([
      trailer({ id: 't1', yardLocation: 'Zone A' }),
      trailer({ id: 't2', yardLocation: 'Zone A' }),
      trailer({ id: 't3', yardLocation: 'Zone B' }),
      trailer({ id: 't4', status: 'in_transit' }),
      trailer({ id: 't5', status: 'outbound' }),
      trailer({ id: 't6', assignedDoorId: 'd9' }),   // docked -> shown on the door
      trailer({ id: 't7' }),                         // no location -> Unassigned
    ])
    expect(zones['Zone A']).toHaveLength(2)
    expect(zones['Zone B']).toHaveLength(1)
    expect(zones['Unassigned']).toHaveLength(1)
    expect(Object.keys(zones)).not.toContain('__docked__')
  })
})

describe('YardMapPanel', () => {
  it('shows doors with occupancy and zones with trailers', () => {
    const onClick = vi.fn()
    const docked = trailer({ id: 't6', trailerId: 'TRL-6', status: 'docked', assignedDoorId: 'd2' })
    render(
      <YardMapPanel
        doors={[door({ id: 'd1' }), door({ id: 'd2', doorNumber: '2', status: 'occupied' })]}
        trailers={[trailer({ id: 't1', yardLocation: 'Zone A' }), docked]}
        onTrailerClick={onClick}
      />
    )
    expect(screen.getByTestId('door-d1')).toBeInTheDocument()
    // docked trailer renders on its door and is clickable
    fireEvent.click(screen.getByText('TRL-6'))
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ id: 't6' }))
    expect(screen.getByTestId('zone-Zone A')).toBeInTheDocument()
  })

  it('renders empty states', () => {
    render(<YardMapPanel doors={[]} trailers={[]} />)
    expect(screen.getByText(/No dock doors configured/)).toBeInTheDocument()
    expect(screen.getByText(/No trailers in the yard/)).toBeInTheDocument()
  })
})
