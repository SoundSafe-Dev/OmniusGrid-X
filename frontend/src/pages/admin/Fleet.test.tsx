/**
 * The OTA fleet page — releases, rollouts, and the version distribution across the estate.
 *
 * The second of the two pages the barrel hid (see `ErrorTriage.test.tsx` and
 * `everyRoutedPageHasATest.test.ts`). At 574 lines it is the largest page that had no test.
 *
 * Its three lists each distinguish loading, failed and empty, which is the property worth
 * holding: "No releases created yet" and "Failed to load releases" are opposite claims, and
 * an operator who reads the first when the second is true concludes the fleet has never been
 * given a release.
 *
 * It also carries FS-480's error card. Six OTA mutations live in `useFleet.ts` and every one
 * of them reported failure to nobody, because both mutation sweeps scanned `.tsx` and hooks
 * are `.ts`. **Yank is the one that matters**: it pulls a release that is going badly, and a
 * failed yank left the release listed exactly as it was — which is also what a successful
 * yank looks like for the moment before the list refetches. The card names which action
 * failed, because "something went wrong" leaves an operator unsure whether the bad release
 * is still going out.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const versions = vi.fn()
const releases = vi.fn()
const rollouts = vi.fn()
const idle = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false })
const mutations = {
  createRelease: idle(),
  publishRelease: idle(),
  yankRelease: idle(),
  createRollout: idle(),
  cancelRollout: idle(),
}

vi.mock('../../hooks/useFleet', () => ({
  useAgentVersions: () => versions(),
  useAgentReleases: () => releases(),
  useAgentRollouts: () => rollouts(),
  useCreateAgentRelease: () => mutations.createRelease,
  usePublishAgentRelease: () => mutations.publishRelease,
  useYankAgentRelease: () => mutations.yankRelease,
  useCreateAgentRollout: () => mutations.createRollout,
  useCancelAgentRollout: () => mutations.cancelRollout,
}))

const { Fleet } = await import('./Fleet')
const { TooltipProvider } = await import('../../components/ui')

const query = (data: unknown, over: Record<string, unknown> = {}) => ({
  data,
  isLoading: false,
  isError: false,
  refetch: vi.fn(),
  ...over,
})

// Shapes taken from `src/types/fleet.ts`, not guessed — a wrong fixture throws inside the
// page and renders an empty document, which reads as a component bug rather than a test
// that made something up.
const release = (over: Record<string, unknown> = {}) => ({
  id: 'rel-1',
  organization_id: 'org-1',
  version: '1.4.0',
  channel: 'stable',
  image_tag: 'opsgrid/agent:1.4.0',
  checksum_sha256: 'a'.repeat(64),
  signature_ed25519: 'sig',
  signing_key_id: 'key-1',
  release_notes: null,
  status: 'published',
  created_by: 'admin',
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  ...over,
})

const rollout = (over: Record<string, unknown> = {}) => ({
  id: 'ro-1',
  organization_id: 'org-1',
  release_id: 'rel-1',
  name: 'agent 1.4.0 → stable',
  target_selector: { all: true },
  strategy: {},
  status: 'running',
  created_by: 'admin',
  created_at: '2026-08-02T00:00:00Z',
  updated_at: '2026-08-02T00:00:00Z',
  targets: [],
  events: [],
  ...over,
})

const show = () =>
  render(
    <MemoryRouter>
      <TooltipProvider>
        <Fleet />
      </TooltipProvider>
    </MemoryRouter>,
  )

beforeEach(() => {
  versions.mockReset()
  releases.mockReset()
  rollouts.mockReset()
  for (const key of Object.keys(mutations) as (keyof typeof mutations)[]) {
    mutations[key] = idle()
  }
  versions.mockReturnValue(
    query({
      items: [
        {
          agent_version: '1.4.0',
          asset_count: 12,
          agent_count: 12,
          latest_heartbeat: '2026-08-06T09:00:00Z',
        },
      ],
    }),
  )
  releases.mockReturnValue(query([release()]))
  rollouts.mockReturnValue(query([rollout()]))
})

describe('a failed OTA action names itself (FS-480)', () => {
  it('says the release is still published when a yank fails', () => {
    // The sharp one. A yank pulls a release that is going badly; "still there" is exactly
    // what a successful yank looks like for the moment before the list refetches, so
    // silence here reads as success while the bad release keeps going out.
    mutations.yankRelease = { ...idle(), isError: true }
    show()

    const alert = screen.getByRole('alert')
    expect(alert.textContent).toMatch(/could not yank/i)
    expect(alert.textContent).toMatch(/still published/i)
  })

  it('names publish separately from yank', () => {
    // Different promises to the operator. "Something went wrong" leaves them unsure which
    // state the fleet is in.
    mutations.publishRelease = { ...idle(), isError: true }
    show()

    expect(screen.getByRole('alert').textContent).toMatch(/could not publish/i)
  })

  it('says nothing was started when a rollout fails', () => {
    mutations.createRollout = { ...idle(), isError: true }
    show()

    expect(screen.getByRole('alert').textContent).toMatch(/nothing was started/i)
  })

  it('says nothing when no action failed', () => {
    // The other direction: a card on every render would make the failures above
    // indistinguishable from the ordinary case.
    show()
    expect(screen.queryByText(/could not yank/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/could not publish/i)).not.toBeInTheDocument()
  })
})

describe('an empty list is not a failed one', () => {
  it('distinguishes them for releases', () => {
    releases.mockReturnValue(query(undefined, { isError: true }))
    show()

    expect(screen.getByText(/failed to load releases/i)).toBeInTheDocument()
    // "No releases created yet" tells an operator the fleet has never been given one.
    expect(screen.queryByText(/no releases created yet/i)).not.toBeInTheDocument()
  })

  it('says the list really is empty when it is', () => {
    releases.mockReturnValue(query([]))
    show()

    expect(screen.getByText(/no releases created yet/i)).toBeInTheDocument()
    expect(screen.queryByText(/failed to load releases/i)).not.toBeInTheDocument()
  })

  it('distinguishes them for rollouts', () => {
    rollouts.mockReturnValue(query(undefined, { isError: true }))
    show()

    expect(screen.getByText(/failed to load rollouts/i)).toBeInTheDocument()
  })

  it('distinguishes them for the version distribution', () => {
    // This one is the estate's own report of what it is running. An empty table reads as
    // "no agent has checked in", which is a fleet-wide outage; a failed query is not.
    versions.mockReturnValue(query(undefined, { isError: true }))
    show()

    expect(screen.getByText(/failed to load version distribution/i)).toBeInTheDocument()
    expect(screen.queryByText(/no agent heartbeats have been recorded/i)).not.toBeInTheDocument()
  })

  it('says so when no agent has actually checked in', () => {
    versions.mockReturnValue(query({ items: [] }))
    show()

    expect(screen.getByText(/no agent heartbeats have been recorded/i)).toBeInTheDocument()
  })
})

describe('the page renders what loaded', () => {
  it('lists a release and a rollout', () => {
    show()
    // `1.4.0` appears in both the version-distribution table and the releases list, which
    // is correct — `getAllByText` rather than a narrower query that would silently stop
    // covering one of them if the layout changed.
    expect(screen.getAllByText('1.4.0').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText(/agent 1.4.0 → stable/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
