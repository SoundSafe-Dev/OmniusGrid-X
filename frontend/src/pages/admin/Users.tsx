import { FC, FormEvent, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  Edit,
  MailPlus,
  Power,
  PowerOff,
  RefreshCw,
  Send,
  X,
} from 'lucide-react';

import { authApi, handleApiError } from '../../api';
import {
  Badge,
  Button,
  Card,
  Input,
  Select,
  SkeletonTable,
  Table,
} from '../../components';
import { useDialog } from '../../components/ui';
import { useAuthStore } from '../../stores';
import { User, UserInvitation, UserRole } from '../../types';


const ROLE_OPTIONS = [
  { value: 'admin', label: 'Admin' },
  { value: 'operator', label: 'Operator' },
  { value: 'viewer', label: 'Viewer' },
];

const formatDate = (value?: string | null) => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString();
};

const invitationStatusVariant = (
  invitation: UserInvitation
): 'success' | 'warning' | 'error' | 'neutral' => {
  if (invitation.status === 'accepted') return 'success';
  if (invitation.status === 'pending') {
    return invitation.deliveryStatus === 'failed' ? 'error' : 'warning';
  }
  return 'neutral';
};

interface ModalProps {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  footer: React.ReactNode;
}

const Modal: FC<ModalProps> = ({ title, children, onClose, footer }) => (
  <div
    className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    role="dialog"
    aria-modal="true"
    aria-label={title}
  >
    <div className="w-full max-w-md rounded-lg border border-opsgrid-border bg-opsgrid-panel">
      <div className="flex items-center justify-between border-b border-opsgrid-border p-6">
        <h3 className="text-xl font-semibold">{title}</h3>
        <button
          type="button"
          onClick={onClose}
          className="text-opsgrid-text-secondary hover:text-opsgrid-text"
          aria-label={`Close ${title}`}
        >
          <X className="h-5 w-5" />
        </button>
      </div>
      <div className="space-y-4 p-6">{children}</div>
      <div className="flex justify-end gap-3 border-t border-opsgrid-border p-6">
        {footer}
      </div>
    </div>
  </div>
);

//: The server's own ceiling on `GET /auth/users` (`le=200`). Asking for more is a 422, not
//: a bigger page — see the note at the query below.
const USER_PAGE_CAP = 200;

//: One page, and the step "Show more" takes. The server declares `le=200`, so the cap
//: above is a real ceiling rather than a client preference — the page has to say so when
//: it reaches it, or an admin reads a truncated list as the whole organisation.
const USER_PAGE_SIZE = 50;

export const UsersPage: FC = () => {
  const { confirm, alert } = useDialog();
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((state) => state.user);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showInvite, setShowInvite] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [inviteForm, setInviteForm] = useState({
    email: '',
    role: 'viewer' as UserRole,
  });
  const [editForm, setEditForm] = useState({
    name: '',
    email: '',
    role: 'viewer' as UserRole,
  });

  // PAGINATED, and the limit is EXPLICIT. The endpoint's default page is not this page's
  // decision to inherit — an undeclared limit means the server picks, and the client then
  // renders whatever arrives as though it were everything.
  const [limit, setLimit] = useState(USER_PAGE_SIZE);
  const usersQuery = useQuery({
    queryKey: ['admin-users', limit],
    // Never above USER_PAGE_CAP: `GET /auth/users` declares `le=200`, so a larger request
    // is rejected 422 and this page renders nothing at all.
    queryFn: () => authApi.getUsers({ limit }),
  });
  const invitationsQuery = useQuery({
    queryKey: ['admin-user-invitations'],
    queryFn: () => authApi.getInvitations({ limit: USER_PAGE_CAP }),
  });

  const reportError = (value: unknown) => {
    setNotice(null);
    setError(handleApiError(value).message);
  };

  const refreshData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['admin-users'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-user-invitations'] }),
    ]);
  };

  const inviteMutation = useMutation({
    mutationFn: authApi.inviteUser,
    onSuccess: async (invitation) => {
      await refreshData();
      setError(null);
      setNotice(
        invitation.deliveryStatus === 'sent'
          ? `Invitation sent to ${invitation.email}.`
          : `Invitation created for ${invitation.email}, but email delivery failed. You can resend it.`
      );
      setInviteForm({ email: '', role: 'viewer' });
      setShowInvite(false);
    },
    onError: reportError,
  });

  const updateMutation = useMutation({
    mutationFn: ({
      userId,
      changes,
    }: {
      userId: string;
      changes: { name: string; email: string; role: UserRole };
    }) => authApi.updateUser(userId, changes),
    onSuccess: async () => {
      await refreshData();
      setError(null);
      setNotice('User details updated.');
      setEditingUser(null);
    },
    onError: reportError,
  });

  const deactivateMutation = useMutation({
    mutationFn: authApi.deactivateUser,
    onSuccess: async (user) => {
      await refreshData();
      setError(null);
      setNotice(`${user.name || user.email} was deactivated.`);
    },
    onError: reportError,
  });

  const reactivateMutation = useMutation({
    mutationFn: authApi.reactivateUser,
    onSuccess: async (user) => {
      await refreshData();
      setError(null);
      setNotice(`${user.name || user.email} was reactivated.`);
    },
    onError: reportError,
  });

  const resendMutation = useMutation({
    mutationFn: authApi.resendInvitation,
    onSuccess: async (invitation) => {
      await refreshData();
      setError(null);
      setNotice(
        invitation.deliveryStatus === 'sent'
          ? `A new invitation link was sent to ${invitation.email}.`
          : `The invitation link was rotated, but email delivery failed.`
      );
    },
    onError: reportError,
  });

  const revokeMutation = useMutation({
    mutationFn: authApi.revokeInvitation,
    onSuccess: async (invitation) => {
      await refreshData();
      setError(null);
      setNotice(`Invitation for ${invitation.email} was revoked.`);
    },
    onError: reportError,
  });

  const submitInvite = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    inviteMutation.mutate({
      email: inviteForm.email.trim().toLowerCase(),
      role: inviteForm.role,
    });
  };

  const openEdit = (user: User) => {
    setError(null);
    setEditingUser(user);
    setEditForm({
      name: user.name,
      email: user.email,
      role: user.role,
    });
  };

  const submitEdit = (event: FormEvent) => {
    event.preventDefault();
    if (!editingUser) return;
    updateMutation.mutate({
      userId: editingUser.id,
      changes: {
        name: editForm.name.trim(),
        email: editForm.email.trim().toLowerCase(),
        role: editForm.role,
      },
    });
  };

  const deactivate = async (user: User) => {
    // DEACTIVATION, not deletion, and the wording says so. The row is kept — alarms and
    // alarm_rules reference the user — so telling an admin they are about to "delete"
    // someone describes an outcome the server will not produce.
    const confirmed = await confirm({
      title: 'Deactivate this user?',
      message:
        `${user.name || user.email} will be DEACTIVATED, not deleted. Their current ` +
        'sessions are revoked and they can be reactivated later.',
      confirmLabel: 'Deactivate',
      // The dialog styles the action as destructive. It is NOT irreversible — the row is
      // kept and the user can be reactivated — which is why the message says deactivated
      // rather than promising something the server will not do.
      destructive: true,
    });
    if (!confirmed) return;
    try {
      await deactivateMutation.mutateAsync(user.id);
    } catch (failure) {
      // reportError already set the banner; this stops the rejection escaping as an
      // unhandled promise and tells the admin the access is UNCHANGED rather than
      // leaving them to infer it from a row that did not move.
      //
      // THE SERVER'S REASON IS CARRIED THROUGH. "It failed" and "you are not allowed to do
      // this" send an admin to different places, and only one of them is worth a retry.
      await alert({
        title: 'The user was not deactivated',
        message:
          `${handleApiError(failure).message}\n\n${user.name || user.email} still has ` +
          'access — nothing has been changed.',
      });
    }
  };

  const revokeInvitation = async (invitation: UserInvitation) => {
    const confirmed = await confirm({
      title: 'Revoke this invitation?',
      message: `The invitation for ${invitation.email} will stop working immediately.`,
      confirmLabel: 'Revoke',
    });
    if (confirmed) revokeMutation.mutate(invitation.id);
  };

  const loading = usersQuery.isLoading || invitationsQuery.isLoading;
  const queryError = usersQuery.error || invitationsQuery.error;
  const queryErrorMessage = queryError
    ? handleApiError(queryError).message
    : null;
  const users = usersQuery.data?.items ?? [];
  const invitations = invitationsQuery.data?.items ?? [];

  const totalUsers = usersQuery.data?.total ?? users.length;
  const hiddenUsers = Math.max(0, totalUsers - users.length);
  const atCeiling = limit >= USER_PAGE_CAP;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">User Management</h2>
          <p className="text-sm text-opsgrid-text-secondary">
            Invite teammates, assign roles, and revoke access for this organization.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            onClick={() => void refreshData()}
            tooltip="Refresh users and invitations"
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Button onClick={() => setShowInvite(true)}>
            <MailPlus className="mr-2 h-4 w-4" />
            Invite User
          </Button>
        </div>
      </div>

      {(error || queryErrorMessage) && (
        <div className="flex items-center gap-2 rounded-lg border border-status-alarm/30 bg-status-alarm/10 p-3 text-status-alarm">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <span className="text-sm">
            {error || queryErrorMessage}
          </span>
        </div>
      )}
      {notice && (
        <div className="rounded-lg border border-status-running/30 bg-status-running/10 p-3 text-sm text-status-running">
          {notice}
        </div>
      )}

      <Card
        title="Organization users"
        subtitle={`${usersQuery.data?.total ?? 0} account${usersQuery.data?.total === 1 ? '' : 's'}`}
        noPadding
      >
        {loading ? (
          <SkeletonTable rows={5} columns={5} />
        ) : (
          <Table>
            <Table.Head>
              <Table.Row>
                <Table.Header>Name</Table.Header>
                <Table.Header>Email</Table.Header>
                <Table.Header>Role</Table.Header>
                <Table.Header>Status</Table.Header>
                <Table.Header className="text-right">Actions</Table.Header>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {users.length === 0 ? (
                <Table.Row>
                  <Table.Cell colSpan={5} className="py-8 text-center text-opsgrid-text-secondary">
                    No users found.
                  </Table.Cell>
                </Table.Row>
              ) : (
                users.map((user) => {
                  const isSelf = user.id === currentUser?.id;
                  return (
                    <Table.Row key={user.id}>
                      <Table.Cell className="font-medium">
                        {user.name || 'Unnamed user'}
                        {isSelf && (
                          <span className="ml-2 text-xs text-opsgrid-text-secondary">
                            You
                          </span>
                        )}
                      </Table.Cell>
                      <Table.Cell>{user.email}</Table.Cell>
                      <Table.Cell>
                        <Badge variant="info">{user.role}</Badge>
                      </Table.Cell>
                      <Table.Cell>
                        <Badge variant={user.isActive ? 'success' : 'neutral'}>
                          {user.isActive ? 'Active' : 'Inactive'}
                        </Badge>
                      </Table.Cell>
                      <Table.Cell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openEdit(user)}
                            aria-label={`Edit ${user.name || user.email}`}
                            tooltip="Edit profile and role"
                          >
                            <Edit className="h-4 w-4" />
                          </Button>
                          {user.isActive ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={isSelf || deactivateMutation.isPending}
                              onClick={() => deactivate(user)}
                              aria-label={`Deactivate ${user.name || user.email}`}
                              tooltip={
                                isSelf
                                  ? 'You cannot deactivate your own account'
                                  : 'Deactivate and revoke all sessions'
                              }
                            >
                              <PowerOff className="h-4 w-4 text-status-alarm" />
                            </Button>
                          ) : (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={reactivateMutation.isPending}
                              onClick={() => reactivateMutation.mutate(user.id)}
                              aria-label={`Reactivate ${user.name || user.email}`}
                              tooltip="Reactivate account without restoring old sessions"
                            >
                              <Power className="h-4 w-4 text-status-running" />
                            </Button>
                          )}
                        </div>
                      </Table.Cell>
                    </Table.Row>
                  );
                })
              )}
            </Table.Body>
          </Table>
        )}
        {/* WHAT IS NOT ON SCREEN, said out loud. A list that stops at the page size and
            offers nothing is indistinguishable from an organisation that small — and an
            admin who believes they are looking at everyone stops looking for the person
            who is missing. `MAX_UNSIGNALLED` is at zero for exactly this class. */}
        {!loading && hiddenUsers > 0 && (
          <div className="flex items-center justify-between gap-3 px-4 py-3 text-xs text-opsgrid-text-secondary">
            <span>
              Showing {users.length} of {totalUsers} users
              {atCeiling && ' — Showing the first 200; narrow the list to see the rest'}
            </span>
            {!atCeiling && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setLimit((n) => Math.min(n + USER_PAGE_SIZE, USER_PAGE_CAP))}
              >
                Show more
              </Button>
            )}
          </div>
        )}
              </Card>

      <Card
        title="Invitations"
        subtitle="One-time links and their delivery status"
        noPadding
      >
        {loading ? (
          <SkeletonTable rows={4} columns={6} />
        ) : (
          <Table>
            <Table.Head>
              <Table.Row>
                <Table.Header>Email</Table.Header>
                <Table.Header>Role</Table.Header>
                <Table.Header>Status</Table.Header>
                <Table.Header>Delivery</Table.Header>
                <Table.Header>Expires</Table.Header>
                <Table.Header className="text-right">Actions</Table.Header>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {invitationsQuery.isError ? (
                /* A FAILED READ IS NOT AN EMPTY LIST. "No invitations yet." is a claim about
                   the organisation; a failed request supports no claim at all, and an admin
                   who reads it stops chasing an invitation that may well be outstanding.
                   Same fix as FS-482 and the failureIsNotEmptiness sweep. */
                <Table.Row>
                  <Table.Cell colSpan={6} className="py-8 text-center text-status-alarm" role="alert">
                    Invitations could not be loaded — this is a loading failure, not an
                    absence of invitations.
                  </Table.Cell>
                </Table.Row>
              ) : invitations.length === 0 ? (
                <Table.Row>
                  <Table.Cell colSpan={6} className="py-8 text-center text-opsgrid-text-secondary">
                    No invitations yet.
                  </Table.Cell>
                </Table.Row>
              ) : (
                invitations.map((invitation) => (
                  <Table.Row key={invitation.id}>
                    <Table.Cell className="font-medium">
                      {invitation.email}
                    </Table.Cell>
                    <Table.Cell>
                      <Badge variant="info">{invitation.role}</Badge>
                    </Table.Cell>
                    <Table.Cell>
                      <Badge variant={invitationStatusVariant(invitation)}>
                        {invitation.status}
                      </Badge>
                    </Table.Cell>
                    <Table.Cell>
                      <div>
                        <span className="capitalize">{invitation.deliveryStatus}</span>
                        {invitation.deliveryStatus === 'failed' && (
                          <p className="text-xs text-status-alarm">
                            {invitation.deliveryErrorCode === 'smtp_not_configured'
                              ? 'SMTP is not configured'
                              : 'SMTP delivery failed'}
                          </p>
                        )}
                      </div>
                    </Table.Cell>
                    <Table.Cell>{formatDate(invitation.expiresAt)}</Table.Cell>
                    <Table.Cell className="text-right">
                      {invitation.status === 'pending' ? (
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={resendMutation.isPending}
                            onClick={() => resendMutation.mutate(invitation.id)}
                            aria-label={`Resend invitation to ${invitation.email}`}
                            tooltip="Rotate the link and send a new invitation"
                          >
                            <Send className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={revokeMutation.isPending}
                            onClick={() => revokeInvitation(invitation)}
                            aria-label={`Revoke invitation for ${invitation.email}`}
                            tooltip="Revoke this invitation"
                          >
                            <X className="h-4 w-4 text-status-alarm" />
                          </Button>
                        </div>
                      ) : (
                        <span className="text-opsgrid-text-secondary">—</span>
                      )}
                    </Table.Cell>
                  </Table.Row>
                ))
              )}
            </Table.Body>
          </Table>
        )}
      </Card>

      {showInvite && (
        <form onSubmit={submitInvite}>
          <Modal
            title="Invite User"
            onClose={() => setShowInvite(false)}
            footer={
              <>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setShowInvite(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" loading={inviteMutation.isPending}>
                  Send Invitation
                </Button>
              </>
            }
          >
            <Input
              label="Email"
              type="email"
              autoComplete="email"
              required
              value={inviteForm.email}
              onChange={(event) =>
                setInviteForm({ ...inviteForm, email: event.target.value })
              }
              helperText="The user will set their name and password through a one-time link."
            />
            <Select
              label="Role"
              value={inviteForm.role}
              onChange={(event) =>
                setInviteForm({
                  ...inviteForm,
                  role: event.target.value as UserRole,
                })
              }
              options={ROLE_OPTIONS}
            />
          </Modal>
        </form>
      )}

      {editingUser && (
        <form onSubmit={submitEdit}>
          <Modal
            title="Edit User"
            onClose={() => setEditingUser(null)}
            footer={
              <>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setEditingUser(null)}
                >
                  Cancel
                </Button>
                <Button type="submit" loading={updateMutation.isPending}>
                  Save Changes
                </Button>
              </>
            }
          >
            <Input
              label="Name"
              required
              value={editForm.name}
              onChange={(event) =>
                setEditForm({ ...editForm, name: event.target.value })
              }
            />
            <Input
              label="Email"
              type="email"
              autoComplete="email"
              required
              value={editForm.email}
              onChange={(event) =>
                setEditForm({ ...editForm, email: event.target.value })
              }
            />
            <Select
              label="Role"
              value={editForm.role}
              disabled={editingUser.id === currentUser?.id}
              helperText={
                editingUser.id === currentUser?.id
                  ? 'You cannot change your own role.'
                  : 'Changing a role revokes the user’s active sessions.'
              }
              onChange={(event) =>
                setEditForm({
                  ...editForm,
                  role: event.target.value as UserRole,
                })
              }
              options={ROLE_OPTIONS}
            />
          </Modal>
        </form>
      )}
    </div>
  );
};
