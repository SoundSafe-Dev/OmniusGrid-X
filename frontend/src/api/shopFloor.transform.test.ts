import { describe, expect, it } from 'vitest'
import { toCamel, toSnake } from './transform'

// The casing seam converts object KEYS recursively. That is right for field names and wrong
// for maps whose keys are DATA — and the shop-floor and activation responses carry three of
// them: `by_status` (keyed by posting status), `posting_statuses` (same), and `routing`
// (keyed by event type and by correlation domain).
//
// The failure is silent, which is why it needs a test rather than a comment. `manual_required`
// becomes `manualRequired`, `STATUS_LABEL[status]` misses, and the panel renders the raw key
// next to a count — a page that looks populated and reads wrong. `OPAQUE_KEYS` in transform.ts
// exists for exactly this; these pin the three entries so a later tidy-up cannot drop them.

describe('status-keyed maps survive the casing seam', () => {
  it('keeps posting-status keys intact in by_status', () => {
    const wire = {
      event_type: 'part_issue',
      fully_posted: false,
      by_status: { pending: 2, manual_required: 1, not_applicable: 1 },
    }
    const out = toCamel<any>(wire)

    // Field names ARE converted...
    expect(out.eventType).toBe('part_issue')
    expect(out.fullyPosted).toBe(false)
    // ...and the map's data keys are not.
    expect(out.byStatus).toEqual({ pending: 2, manual_required: 1, not_applicable: 1 })
    expect(out.byStatus.manualRequired).toBeUndefined()
  })

  it('keeps them intact on the way back out', () => {
    const out = toSnake<any>({ byStatus: { manual_required: 1 } })
    expect(out.by_status).toEqual({ manual_required: 1 })
  })

  it('keeps the status descriptions keyed by status', () => {
    const out = toCamel<any>({
      posting_statuses: {
        manual_required: 'no integration for this target — a person must be told',
        not_applicable: 'this deployment deliberately does not route here',
      },
    })
    expect(Object.keys(out.postingStatuses).sort()).toEqual([
      'manual_required',
      'not_applicable',
    ])
  })

  it('keeps routing keyed by event type and by domain', () => {
    const out = toCamel<any>({
      routing: {
        part_issue: ['inventory', 'purchasing', 'accounting'],
        QUALITY_CONTROL: ['quality', 'production'],
      },
      target_systems: ['inventory'],
    })
    expect(out.routing.part_issue).toEqual(['inventory', 'purchasing', 'accounting'])
    expect(out.routing.QUALITY_CONTROL).toEqual(['quality', 'production'])
    // The surrounding field name is still converted.
    expect(out.targetSystems).toEqual(['inventory'])
  })
})
