import { beforeEach, describe, expect, it, vi } from 'vitest'

// Stub the api barrel so importing the store doesn't pull axios/all clients.
vi.mock('../api', () => ({
  authApi: { login: vi.fn(), logout: vi.fn().mockResolvedValue(undefined) },
}))

import { useAuthStore } from './authStore'

function reset() {
  useAuthStore.setState({
    user: null,
    accessToken: null,
    refreshToken: null,
    isAuthenticated: false,
    isLoading: false,
    error: null,
  })
  localStorage.clear()
}

describe('authStore', () => {
  beforeEach(reset)

  it('starts unauthenticated', () => {
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })

  it('devLogin authenticates and stores the token', () => {
    const user = { id: '1', name: 'Dev', email: 'd@x.io', roles: [] } as any
    useAuthStore.getState().devLogin(user, 'tok-123')
    const s = useAuthStore.getState()
    expect(s.isAuthenticated).toBe(true)
    expect(s.accessToken).toBe('tok-123')
    expect(s.user?.email).toBe('d@x.io')
  })

  it('logout clears auth state', async () => {
    const user = { id: '1', name: 'Dev', email: 'd@x.io', roles: [] } as any
    useAuthStore.getState().devLogin(user, 'tok-123')
    await useAuthStore.getState().logout()
    const s = useAuthStore.getState()
    expect(s.isAuthenticated).toBe(false)
    expect(s.user).toBeNull()
    expect(s.accessToken).toBeNull()
  })

  it('hasPermission is false with no user', () => {
    expect(useAuthStore.getState().hasPermission('assets', 'read')).toBe(false)
  })
})
