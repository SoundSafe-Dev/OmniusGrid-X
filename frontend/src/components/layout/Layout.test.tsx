import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

// Only the app root had an ErrorBoundary, so a render crash in any page blanked
// the entire app (shell included). Layout now wraps the route Outlet in a
// per-route boundary: a page crash shows a scoped fallback while the sidebar
// and header stay usable.

vi.mock('./Sidebar', () => ({ Sidebar: () => <nav>SIDEBAR</nav> }))
vi.mock('./Header', () => ({ Header: () => <header>HEADER</header> }))

import { Layout } from './Layout'

const Boom = () => {
  throw new Error('page render crash')
}

function renderAt(path: string, element: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/ok" element={<div>HEALTHY PAGE</div>} />
          <Route path="/boom" element={element} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('Layout per-route error boundary', () => {
  // ErrorBoundary + React log caught render errors; keep the test output clean.
  beforeEach(() => vi.spyOn(console, 'error').mockImplementation(() => {}))
  afterEach(() => vi.restoreAllMocks())

  it('contains a page crash and keeps the shell usable', () => {
    renderAt('/boom', <Boom />)
    expect(screen.getByRole('alert')).toHaveTextContent(/unexpected error/i)
    // The shell survives — this is the whole point of a scoped boundary.
    expect(screen.getByText('SIDEBAR')).toBeInTheDocument()
    expect(screen.getByText('HEADER')).toBeInTheDocument()
  })

  it('renders a healthy page normally (no false fallback)', () => {
    renderAt('/ok', <div>unused</div>)
    expect(screen.getByText('HEALTHY PAGE')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
