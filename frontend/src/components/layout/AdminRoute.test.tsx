/**
 * Guard tests for AdminRoute.
 *
 * AdminRoute was fully implemented and exported but wired to no route, so all
 * nine /admin/* pages sat behind ProtectedRoute alone and any authenticated
 * user could reach user management, org settings and the edge fleet. There was
 * no test on either route guard, which is how it went unnoticed through the
 * convergence.
 *
 * The last case renders the real App router rather than a hand-built one, so it
 * fails if the guard is ever unwired again.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { AdminRoute } from './AdminRoute';
import { useAuthStore } from '../../stores';
import type { User } from '../../types/auth';

function makeUser(overrides: Partial<User> & Pick<User, 'id' | 'role'>): User {
  return {
    email: `${overrides.id}@example.com`,
    name: overrides.role,
    organizationId: 'org-1',
    isActive: true,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

const admin = makeUser({ id: 'u-admin', role: 'admin' });
const operator = makeUser({ id: 'u-op', role: 'operator' });

function setAuth(state: Partial<ReturnType<typeof useAuthStore.getState>>) {
  useAuthStore.setState(state as never);
}

function renderGuard() {
  return render(
    <MemoryRouter initialEntries={['/admin/users']}>
      <Routes>
        <Route path="/" element={<div>home</div>} />
        <Route path="/login" element={<div>login page</div>} />
        <Route element={<AdminRoute />}>
          <Route path="/admin/users" element={<div>admin users page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('AdminRoute', () => {
  beforeEach(() => {
    setAuth({ user: null, isAuthenticated: false, isLoading: false });
  });

  it('renders the admin page for an admin', () => {
    setAuth({ user: admin, isAuthenticated: true, isLoading: false });
    renderGuard();
    expect(screen.getByText('admin users page')).toBeInTheDocument();
  });

  it('redirects an authenticated non-admin away from the admin page', () => {
    setAuth({ user: operator, isAuthenticated: true, isLoading: false });
    renderGuard();
    expect(screen.queryByText('admin users page')).not.toBeInTheDocument();
    expect(screen.getByText('home')).toBeInTheDocument();
  });

  it('redirects an unauthenticated visitor to login', () => {
    setAuth({ user: null, isAuthenticated: false, isLoading: false });
    renderGuard();
    expect(screen.queryByText('admin users page')).not.toBeInTheDocument();
    expect(screen.getByText('login page')).toBeInTheDocument();
  });

  it('shows a loading state rather than deciding while auth is resolving', () => {
    setAuth({ user: null, isAuthenticated: false, isLoading: true });
    renderGuard();
    expect(screen.queryByText('admin users page')).not.toBeInTheDocument();
    expect(screen.queryByText('login page')).not.toBeInTheDocument();
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });
});

describe('App router wiring', () => {
  /**
   * The behavioural tests above pass whether or not App.tsx actually uses the
   * guard — which was precisely the bug. This asserts the wiring itself: every
   * /admin/* route must live inside the <Route element={<AdminRoute />}> block.
   */
  it('nests every /admin route inside AdminRoute', () => {
    // vitest runs with the frontend package root as cwd.
    const source = readFileSync(resolve(process.cwd(), 'src/App.tsx'), 'utf8');

    const adminPaths = [...source.matchAll(/path="(\/admin\/[^"]*)"/g)].map((m) => m[1]);
    expect(adminPaths.length).toBeGreaterThan(0);

    const guardStart = source.indexOf('<Route element={<AdminRoute />}>');
    expect(guardStart, 'App.tsx does not render <AdminRoute />').toBeGreaterThan(-1);

    // Slice out the guard block by indentation: from the line opening the guard
    // to the `</Route>` closing at the same indent. Tag-counting is unreliable
    // here because JSX attributes contain '>' (element={<AdminRoute />}).
    const guardBlock = (() => {
      const lines = source.split('\n');
      const openIdx = lines.findIndex((l) => l.includes('<Route element={<AdminRoute />}>'));
      if (openIdx === -1) return '';
      const indent = lines[openIdx].length - lines[openIdx].trimStart().length;
      for (let i = openIdx + 1; i < lines.length; i += 1) {
        const line = lines[i];
        const lineIndent = line.length - line.trimStart().length;
        if (line.trim() === '</Route>' && lineIndent === indent) {
          return lines.slice(openIdx, i + 1).join('\n');
        }
      }
      return '';
    })();

    expect(guardBlock, 'could not find the end of the AdminRoute block').not.toBe('');
    for (const path of adminPaths) {
      expect(guardBlock, `${path} is not inside the AdminRoute block`).toContain(`path="${path}"`);
    }
  });
});
