import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '../../components/ui';
import type { User, UserInvitation } from '../../types';

const authApiMocks = vi.hoisted(() => ({
  getUsers: vi.fn(),
  getInvitations: vi.fn(),
  inviteUser: vi.fn(),
  updateUser: vi.fn(),
  deactivateUser: vi.fn(),
  reactivateUser: vi.fn(),
  resendInvitation: vi.fn(),
  revokeInvitation: vi.fn(),
}));

vi.mock('../../api', () => ({
  authApi: authApiMocks,
  handleApiError: (error: unknown) => ({
    status: 500,
    message: error instanceof Error ? error.message : 'Request failed',
  }),
}));

import { useAuthStore } from '../../stores';
import { UsersPage } from './Users';

const NOW = '2026-08-03T12:00:00Z';

const admin: User = {
  id: 'admin-1',
  email: 'admin@example.com',
  name: 'Admin User',
  role: 'admin',
  organizationId: 'org-1',
  isActive: true,
  createdAt: NOW,
  updatedAt: NOW,
};

const target: User = {
  id: 'user-2',
  email: 'target@example.com',
  name: 'Target User',
  role: 'operator',
  organizationId: 'org-1',
  isActive: true,
  createdAt: NOW,
  updatedAt: NOW,
};

const inactiveUser: User = {
  id: 'user-3',
  email: 'inactive@example.com',
  name: 'Dormant User',
  role: 'viewer',
  organizationId: 'org-1',
  isActive: false,
  createdAt: NOW,
  updatedAt: NOW,
};

const invitation: UserInvitation = {
  id: 'invite-1',
  email: 'new.user@example.com',
  role: 'operator',
  status: 'pending',
  expiresAt: '2026-08-04T12:00:00Z',
  deliveryStatus: 'sent',
  deliveryAttempts: 1,
  createdBy: admin.id,
  createdAt: NOW,
  updatedAt: NOW,
};

const page = <T,>(items: T[]) => ({
  items,
  total: items.length,
  skip: 0,
  limit: 500,
  hasMore: false,
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return {
    user: userEvent.setup(),
    ...render(
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <UsersPage />
        </TooltipProvider>
      </QueryClientProvider>,
    ),
  };
}

describe('UsersPage organization administration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({
      user: admin,
      accessToken: 'admin-token',
      refreshToken: null,
      isAuthenticated: true,
      isLoading: false,
      error: null,
    });

    authApiMocks.getUsers.mockResolvedValue(
      page([admin, target, inactiveUser]),
    );
    authApiMocks.getInvitations.mockResolvedValue(page([]));
    authApiMocks.inviteUser.mockResolvedValue(invitation);
    authApiMocks.updateUser.mockResolvedValue({
      ...target,
      name: 'Updated User',
      email: 'updated@example.com',
      role: 'admin',
    });
    authApiMocks.deactivateUser.mockResolvedValue({
      ...target,
      isActive: false,
    });
    authApiMocks.reactivateUser.mockResolvedValue({
      ...inactiveUser,
      isActive: true,
    });
  });

  it('invites a user with a normalized email and selected role', async () => {
    const { user } = renderPage();
    await screen.findByText('Target User');

    await user.click(screen.getByRole('button', { name: 'Invite User' }));
    const dialog = screen.getByRole('dialog', { name: 'Invite User' });
    await user.type(
      within(dialog).getByRole('textbox', { name: 'Email' }),
      '  New.User@Example.COM  ',
    );
    await user.selectOptions(within(dialog).getByRole('combobox'), 'operator');
    await user.click(
      within(dialog).getByRole('button', { name: 'Send Invitation' }),
    );

    await waitFor(() => {
      expect(authApiMocks.inviteUser).toHaveBeenCalled();
      expect(authApiMocks.inviteUser.mock.calls[0][0]).toEqual({
        email: 'new.user@example.com',
        role: 'operator',
      });
    });
    expect(
      await screen.findByText('Invitation sent to new.user@example.com.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Invite User' })).toBeNull();
  });

  it('updates profile and role, deactivates, and reactivates users', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { user } = renderPage();
    await screen.findByText('Target User');

    await user.click(
      screen.getByRole('button', { name: 'Edit Target User' }),
    );
    const dialog = screen.getByRole('dialog', { name: 'Edit User' });
    const nameInput = within(dialog).getByRole('textbox', { name: 'Name' });
    const emailInput = within(dialog).getByRole('textbox', { name: 'Email' });
    await user.clear(nameInput);
    await user.type(nameInput, ' Updated User ');
    await user.clear(emailInput);
    await user.type(emailInput, ' Updated@Example.COM ');
    await user.selectOptions(within(dialog).getByRole('combobox'), 'admin');
    await user.click(
      within(dialog).getByRole('button', { name: 'Save Changes' }),
    );

    await waitFor(() => {
      expect(authApiMocks.updateUser).toHaveBeenCalledWith(target.id, {
        name: 'Updated User',
        email: 'updated@example.com',
        role: 'admin',
      });
    });
    expect(await screen.findByText('User details updated.')).toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: 'Deactivate Target User' }),
    );
    expect(confirm).toHaveBeenCalledWith(
      'Deactivate Target User? Their current sessions will be revoked.',
    );
    await waitFor(() => {
      expect(authApiMocks.deactivateUser).toHaveBeenCalled();
      expect(authApiMocks.deactivateUser.mock.calls[0][0]).toBe(target.id);
    });
    expect(
      await screen.findByText('Target User was deactivated.'),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: 'Reactivate Dormant User' }),
    );
    await waitFor(() => {
      expect(authApiMocks.reactivateUser).toHaveBeenCalled();
      expect(authApiMocks.reactivateUser.mock.calls[0][0]).toBe(
        inactiveUser.id,
      );
    });
    expect(
      await screen.findByText('Dormant User was reactivated.'),
    ).toBeInTheDocument();
  });

  it('keeps the displayed user and edit dialog intact when an update fails', async () => {
    authApiMocks.updateUser.mockRejectedValueOnce(
      new Error('Cross-tenant update rejected'),
    );
    const { user } = renderPage();
    await screen.findByText('Target User');

    await user.click(
      screen.getByRole('button', { name: 'Edit Target User' }),
    );
    const dialog = screen.getByRole('dialog', { name: 'Edit User' });
    const nameInput = within(dialog).getByRole('textbox', { name: 'Name' });
    await user.clear(nameInput);
    await user.type(nameInput, 'Should Not Persist');
    await user.click(
      within(dialog).getByRole('button', { name: 'Save Changes' }),
    );

    expect(
      await screen.findByText('Cross-tenant update rejected'),
    ).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Edit User' })).toBeInTheDocument();
    expect(screen.getByText('Target User')).toBeInTheDocument();
    expect(authApiMocks.getUsers).toHaveBeenCalledTimes(1);
  });
});
