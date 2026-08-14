/**
 * The four bounding flags the evidence engine sets on its own output, and whether the page
 * turns each into a sentence a reader sees.
 *
 * WHY A SEPARATE FILE, AND WHAT IT DOES NOT PROVE. The evidence panel that renders these
 * sits behind a multi-step workflow — select intake items, catalog their tables, request a
 * preview — and `IntakeInbox.test.tsx` mocks four API methods, none of them the evidence
 * ones. Driving that flow to reach one paragraph would test the workflow, not the caveat.
 * So the decision logic is tested where it lives and the render site is a single
 * `boundedAnalysisNotes(evidenceResult).length > 0` guard beside it.
 *
 * That means these tests prove the right sentence is PRODUCED for each flag, not that it
 * reaches the screen. The distinction is real and is the reason the guard that found this
 * (`test_qualifiers_reach_the_frontend.py`) says in its own docstring that it can only show
 * the frontend NAMES a qualifier, never that it displays one.
 *
 * The flags were each read from the server that sets them rather than inferred from the
 * name: `sampled` is on `field_signals[*].anomalies` / `.change_point` and on each
 * relationship — NOT on a top-level series list, which is what the first draft of the
 * TypeScript invented.
 */
import { describe, expect, it } from 'vitest'

const { boundedAnalysisNotes } = await import('./IntakeInbox')

describe('a bounded analysis says what it left out', () => {
  it('says nothing when nothing was bounded', () => {
    expect(boundedAnalysisNotes({ selection_mode: 'auto' })).toEqual([])
    expect(boundedAnalysisNotes(null)).toEqual([])
    expect(boundedAnalysisNotes(undefined)).toEqual([])
  })

  it('names a rollup that lists only its first groups', () => {
    const notes = boundedAnalysisNotes({
      selection_mode: 'auto',
      entity_rollups: { rollups: [{ group_count: 400, groups_truncated: true }] },
    })
    expect(notes).toHaveLength(1)
    expect(notes[0]).toMatch(/largest contributor/i)
  })

  it('names a table whose metric breakdowns were capped', () => {
    const notes = boundedAnalysisNotes({
      selection_mode: 'auto',
      entity_rollups: { tables: [{ rollup_count: 20, rollups_truncated: true }] },
    })
    expect(notes).toHaveLength(1)
    expect(notes[0]).toMatch(/missing rather than absent/i)
  })

  it('names analytics that ran over a slice of the rows', () => {
    const notes = boundedAnalysisNotes({
      selection_mode: 'auto',
      operational_analytics: { bounded: { input_truncated: true } },
    })
    expect(notes).toHaveLength(1)
    expect(notes[0]).toMatch(/bounded slice/i)
  })

  it('finds `sampled` on an anomaly block, where the server actually puts it', () => {
    const notes = boundedAnalysisNotes({
      selection_mode: 'auto',
      operational_analytics: {
        field_signals: { downtime_minutes: { anomalies: { sampled: true }, ordering: 'event_time' } },
      },
    })
    expect(notes).toHaveLength(1)
    expect(notes[0]).toMatch(/sampled before analysis/i)
  })

  it('finds `sampled` on a relationship too', () => {
    const notes = boundedAnalysisNotes({
      selection_mode: 'auto',
      operational_analytics: { relationships: [{ left_field: 'a', right_field: 'b', sampled: true }] },
    })
    expect(notes).toHaveLength(1)
  })

  /** One sentence per KIND of bounding, not one per occurrence — a preview with forty
   *  truncated rollups is still one thing the reader needs to know. */
  it('collects every distinct kind and does not repeat one', () => {
    const notes = boundedAnalysisNotes({
      selection_mode: 'auto',
      entity_rollups: {
        rollups: [{ groups_truncated: true }, { groups_truncated: true }],
        tables: [{ rollups_truncated: true }],
      },
      operational_analytics: {
        bounded: { input_truncated: true },
        relationships: [{ sampled: true }, { sampled: true }],
      },
    })
    expect(notes).toHaveLength(4)
    expect(new Set(notes).size).toBe(4)
  })

  it('does not warn when the flags are present and false', () => {
    expect(
      boundedAnalysisNotes({
        selection_mode: 'auto',
        entity_rollups: { rollups: [{ groups_truncated: false }], tables: [{ rollups_truncated: false }] },
        operational_analytics: {
          bounded: { input_truncated: false, pair_limit_reached: true },
          relationships: [{ sampled: false }],
          field_signals: { x: { anomalies: { sampled: false }, change_point: { sampled: false } } },
        },
      }),
    ).toEqual([])
  })
})
