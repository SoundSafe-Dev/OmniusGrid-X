import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '../../components/ui'

const hooks = vi.hoisted(() => {
  const mutation = () => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
  })

  return {
    sites: [] as unknown[],
    workcells: [] as unknown[],
    tags: [] as unknown[],
    groups: [] as unknown[],
    cohorts: [] as unknown[],
    inventory: { assets: [] as unknown[] },
    cohortDetail: undefined as unknown,
    cohortDetailError: false,
    cohortDetailFetching: false,
    cohortRefetch: vi.fn(),
    useFleetCohort: vi.fn(),
    updateSite: mutation(),
    updateTag: mutation(),
    updateGroup: mutation(),
    updateCohort: mutation(),
  }
})

vi.mock('../../hooks/useFleet', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../hooks/useFleet')
  const mutation = () => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
  })
  const query = (data: unknown) => ({
    data,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  })
  const fallback = () => mutation()

  return {
    ...Object.fromEntries(Object.keys(actual).map((name) => [name, fallback])),
    useFleetSites: () => query(hooks.sites),
    useFleetWorkcells: () => query(hooks.workcells),
    useFleetTags: () => query(hooks.tags),
    useFleetGroups: () => query(hooks.groups),
    useFleetCohorts: () => query(hooks.cohorts),
    useFleetInventory: () => query(hooks.inventory),
    useFleetCohort: hooks.useFleetCohort,
    useUpdateFleetSite: () => hooks.updateSite,
    useUpdateFleetTag: () => hooks.updateTag,
    useUpdateFleetGroup: () => hooks.updateGroup,
    useUpdateFleetCohort: () => hooks.updateCohort,
  }
})

vi.mock('../../api', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  authApi: {},
  handleApiError: (error: unknown) => ({
    message: error instanceof Error ? error.message : 'Request failed',
  }),
}))

import { FleetTargeting } from './FleetTargeting'

const site = {
  id: 'site-1',
  key: 'plant-a',
  name: 'Plant A',
  description: 'Primary plant',
  is_active: true,
  created_at: null,
  updated_at: null,
}

const tag = {
  id: 'tag-1',
  key: 'video',
  name: 'Video',
  description: 'Video collectors',
  color: '#2dd4bf',
  is_active: true,
  created_at: null,
  updated_at: null,
}

const group = {
  id: 'group-1',
  key: 'operators',
  name: 'Operators',
  description: null,
  is_active: true,
  created_at: null,
  updated_at: null,
}

const nestedQuery = {
  any_of: [
    { field: 'tag', operator: 'all', value: ['tag-1', 'tag-2'] },
    {
      all_of: [
        { field: 'site_id', operator: 'eq', value: 'site-1' },
        { field: 'agent_version', operator: 'lt', value: '2.1.0' },
      ],
    },
  ],
}

const cohort = {
  id: 'cohort-1',
  name: 'Nested cohort',
  description: 'Canonical filters',
  query_version: 3,
  query: nestedQuery,
  is_active: true,
  created_at: null,
  updated_at: null,
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter>
          <FleetTargeting />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

function resetMutation(mutation: typeof hooks.updateSite) {
  mutation.mutate.mockReset()
  mutation.mutateAsync.mockReset()
  mutation.isPending = false
}

beforeEach(() => {
  hooks.sites = [site]
  hooks.workcells = []
  hooks.tags = [tag]
  hooks.groups = [group]
  hooks.cohorts = [cohort]
  hooks.inventory = { assets: [] }
  hooks.cohortDetail = cohort
  hooks.cohortDetailError = false
  hooks.cohortDetailFetching = false
  hooks.cohortRefetch.mockReset()
  hooks.useFleetCohort.mockReset()
  hooks.useFleetCohort.mockImplementation((cohortId: string) => ({
    data: cohortId ? hooks.cohortDetail : undefined,
    isLoading: Boolean(cohortId) && !hooks.cohortDetail && !hooks.cohortDetailError,
    isFetching: hooks.cohortDetailFetching,
    isError: Boolean(cohortId) && hooks.cohortDetailError,
    refetch: hooks.cohortRefetch,
  }))
  resetMutation(hooks.updateSite)
  resetMutation(hooks.updateTag)
  resetMutation(hooks.updateGroup)
  resetMutation(hooks.updateCohort)
})

describe('FleetTargeting resource editing', () => {
  it('renders safely when every query is empty', () => {
    hooks.sites = []
    hooks.tags = []
    hooks.groups = []
    hooks.cohorts = []

    show()

    expect(screen.queryByText(/undefined|NaN|\[object Object\]/)).not.toBeInTheDocument()
  })

  it('exposes an accessible edit control for every resource type', () => {
    show()

    expect(screen.getByRole('button', { name: 'Edit site Plant A' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Edit tag Video' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Edit group Operators' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Edit cohort Nested cohort' })).toBeEnabled()
  })

  it('updates a site with changed fields and explicitly clears its description', async () => {
    const user = userEvent.setup()
    show()

    await user.click(screen.getByRole('button', { name: 'Edit site Plant A' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit site' })
    const name = within(dialog).getByLabelText('Name')
    const description = within(dialog).getByLabelText('Description')
    await user.clear(name)
    await user.type(name, 'Plant Alpha')
    await user.clear(description)
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))

    expect(hooks.updateSite.mutate).toHaveBeenCalledTimes(1)
    expect(hooks.updateSite.mutate.mock.calls[0][0]).toEqual({
      siteId: 'site-1',
      payload: { name: 'Plant Alpha', description: null },
    })
  })

  it('updates a tag and sends null when its color is cleared', async () => {
    const user = userEvent.setup()
    show()

    await user.click(screen.getByRole('button', { name: 'Edit tag Video' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit tag' })
    await user.clear(within(dialog).getByLabelText('Color'))
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))

    expect(hooks.updateTag.mutate).toHaveBeenCalledTimes(1)
    expect(hooks.updateTag.mutate.mock.calls[0][0]).toEqual({
      tagId: 'tag-1',
      payload: { color: null },
    })
  })

  it('updates a group key through the typed group mutation', async () => {
    const user = userEvent.setup()
    show()

    await user.click(screen.getByRole('button', { name: 'Edit group Operators' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit group' })
    const key = within(dialog).getByLabelText('Key')
    await user.clear(key)
    await user.type(key, 'operators-v2')
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))

    expect(hooks.updateGroup.mutate).toHaveBeenCalledTimes(1)
    expect(hooks.updateGroup.mutate.mock.calls[0][0]).toEqual({
      groupId: 'group-1',
      payload: { key: 'operators-v2' },
    })
  })

  it('fetches cohort detail and omits its nested query from metadata-only edits', async () => {
    const user = userEvent.setup()
    show()

    await user.click(screen.getByRole('button', { name: 'Edit cohort Nested cohort' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit cohort' })
    const query = await within(dialog).findByLabelText('Cohort query (JSON)')
    expect(JSON.parse((query as HTMLTextAreaElement).value)).toEqual(nestedQuery)
    const description = within(dialog).getByLabelText('Description')
    await user.clear(description)
    await user.type(description, 'Updated metadata')
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))

    expect(hooks.useFleetCohort).toHaveBeenCalledWith('cohort-1')
    expect(hooks.updateCohort.mutate).toHaveBeenCalledTimes(1)
    expect(hooks.updateCohort.mutate.mock.calls[0][0]).toEqual({
      cohortId: 'cohort-1',
      payload: { description: 'Updated metadata' },
    })
  })

  it('does not expose a cached cohort query while its canonical detail refreshes', async () => {
    hooks.cohortDetailFetching = true
    const user = userEvent.setup()
    show()

    await user.click(screen.getByRole('button', { name: 'Edit cohort Nested cohort' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit cohort' })

    expect(within(dialog).getByRole('status')).toHaveTextContent(
      'Loading the canonical cohort query',
    )
    expect(within(dialog).queryByLabelText('Cohort query (JSON)')).not.toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })

  it('rejects malformed cohort JSON without calling the mutation', async () => {
    const user = userEvent.setup()
    show()

    await user.click(screen.getByRole('button', { name: 'Edit cohort Nested cohort' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit cohort' })
    const query = await within(dialog).findByLabelText('Cohort query (JSON)')
    await user.clear(query)
    await user.type(query, 'not valid json')
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))

    expect(within(dialog).getByRole('alert')).toHaveTextContent(
      'Cohort query must be valid JSON.',
    )
    expect(hooks.updateCohort.mutate).not.toHaveBeenCalled()
  })

  it('sends a deliberately changed cohort query through the cohort mutation', async () => {
    const replacementQuery = {
      field: 'collector_type',
      operator: 'eq',
      value: 'modbus',
    }
    const user = userEvent.setup()
    show()

    await user.click(screen.getByRole('button', { name: 'Edit cohort Nested cohort' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit cohort' })
    const query = await within(dialog).findByLabelText('Cohort query (JSON)')
    fireEvent.change(query, { target: { value: JSON.stringify(replacementQuery) } })
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))

    expect(hooks.updateCohort.mutate.mock.calls[0][0]).toEqual({
      cohortId: 'cohort-1',
      payload: { query: replacementQuery },
    })
  })

  it('keeps the editor values and displayed row intact when the API fails', async () => {
    hooks.updateSite.mutate.mockImplementation((...args: unknown[]) => {
      const options = args[1] as { onError?: (error: unknown) => void }
      options.onError?.(new Error('A site with that name already exists'))
    })
    const user = userEvent.setup()
    show()

    await user.click(screen.getByRole('button', { name: 'Edit site Plant A' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit site' })
    const name = within(dialog).getByLabelText('Name')
    await user.clear(name)
    await user.type(name, 'Plant Conflict')
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))

    expect(within(dialog).getByRole('alert')).toHaveTextContent(
      'A site with that name already exists',
    )
    expect(within(dialog).getByLabelText('Name')).toHaveValue('Plant Conflict')
    expect(screen.getByRole('button', { name: 'Edit site Plant A' })).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Edit site' })).toBeInTheDocument()
  })

  it('closes the editor and announces the updated resource after success', async () => {
    hooks.updateSite.mutate.mockImplementation((...args: unknown[]) => {
      const variables = args[0] as { payload: { name?: string } }
      const options = args[1] as { onSuccess?: (value: typeof site) => void }
      options.onSuccess?.({ ...site, name: variables.payload.name ?? site.name })
    })
    const user = userEvent.setup()
    show()

    await user.click(screen.getByRole('button', { name: 'Edit site Plant A' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit site' })
    const name = within(dialog).getByLabelText('Name')
    await user.clear(name)
    await user.type(name, 'Plant Alpha')
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByRole('status')).toHaveTextContent('Updated site Plant Alpha.')
  })
})
