import { FC, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Activity, HardDrive, X, Plus, Edit, Trash2 } from 'lucide-react';
import { Card, Badge, Button, Table, SkeletonCard, Input, Select } from '../../components';
import { Tooltip, TooltipTrigger, TooltipContent, useDialog } from '../../components/ui';
import { authApi, api } from '../../api';
import { User, UserRole } from '../../types';

// One page of users. The server caps `limit` at 200, which is also where "Show more"
// stops — beyond that the page says so instead of quietly ending the list.
const PAGE_SIZE = 50;
const MAX_PAGE = 200;

export const UsersPage: FC = () => {
  const queryClient = useQueryClient();
  const { confirm, alert } = useDialog();
  // `limit` is explicit because the endpoint now paginates. It used to return the whole
  // organisation — it declared no query parameters, so the `{ skip, limit }` this client
  // has always sent were dropped silently by FastAPI. Fixing the handler without fixing
  // this page would have swapped one silent truncation for another: the table would show
  // the server's default page and give no sign that anyone was missing.
  const [limit, setLimit] = useState(PAGE_SIZE);
  const { data: users, isLoading, isError } = useQuery({
    queryKey: ['users', limit],
    queryFn: () => authApi.getUsers({ limit }),
  });
  // Enabled in FS-221/224: the admin router at /api/v1/users now provides
  // create / update / deactivate, all admin-gated and tenant-scoped. These
  // affordances were hidden (not merely disabled) while the endpoints 404'd.
  const USER_MGMT_ENABLED = true;
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    role: 'viewer' as UserRole,
    isActive: true,
    password: '',
  });

  const createMutation = useMutation({
    mutationFn: (userData: typeof formData) => authApi.createUser(userData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setShowAddModal(false);
      setFormData({ name: '', email: '', role: 'viewer', isActive: true, password: '' });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ userId, userData }: { userId: string; userData: Partial<User> }) =>
      authApi.updateUser(userId, userData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setShowEditModal(false);
      setSelectedUser(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (userId: string) => authApi.deleteUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });

  const handleAddUser = async () => {
    if (!formData.name || !formData.email || !formData.password) {
      await alert({
        title: 'Missing information',
        message: 'Please fill in all required fields.',
      });
      return;
    }
    createMutation.mutate(formData);
  };

  const handleEditUser = () => {
    if (!selectedUser) return;
    updateMutation.mutate({
      userId: selectedUser.id,
      userData: {
        name: formData.name,
        email: formData.email,
        role: formData.role,
        isActive: formData.isActive,
      },
    });
  };

  const handleDeleteUser = async (userId: string) => {
    // Wording matches what the server actually does. DELETE /users/{id}
    // DEACTIVATES: the row is kept because alarms.acknowledged_by and
    // alarm_rules.created_by reference it, so "this cannot be undone" was false
    // and would have discouraged a reversible, recoverable action.
    const ok = await confirm({
      title: 'Deactivate user',
      message:
        'They will lose access immediately. The account and its history are kept, and an administrator can reactivate it.',
      confirmLabel: 'Deactivate',
      destructive: true,
    });
    if (ok) {
      deleteMutation.mutate(userId);
    }
  };

  const openEditModal = (user: User) => {
    setSelectedUser(user);
    setFormData({
      name: user.name,
      email: user.email,
      role: user.role,
      isActive: user.isActive,
      password: '',
    });
    setShowEditModal(true);
  };

  if (isLoading) return <SkeletonCard lines={5} />;
  if (isError) {
    return (
      <Card className="p-4">
        <p className="text-status-alarm text-sm">Failed to load users. Try again.</p>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">User Management</h2>
          {!USER_MGMT_ENABLED && (
            <p className="text-sm text-opsgrid-text-secondary mt-1">
              User accounts are provisioned by an administrator on the backend —
              self-serve create/edit/delete isn't available yet.
            </p>
          )}
        </div>
        {USER_MGMT_ENABLED && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="primary" onClick={() => setShowAddModal(true)}>
                <Plus className="w-4 h-4 mr-2" />
                Add User
              </Button>
            </TooltipTrigger>
            <TooltipContent>Create a new user account</TooltipContent>
          </Tooltip>
        )}
      </div>

      <Card>
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
            {users?.items.length === 0 && (
              <Table.Row>
                <Table.Cell colSpan={5} className="text-center text-opsgrid-text-secondary">
                  No users found.
                </Table.Cell>
              </Table.Row>
            )}
            {users?.items.map((user: User) => (
              <Table.Row key={user.id}>
                <Table.Cell className="font-medium">{user.name}</Table.Cell>
                <Table.Cell>{user.email}</Table.Cell>
                <Table.Cell>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge variant="info" size="sm">{user.role}</Badge>
                    </TooltipTrigger>
                    <TooltipContent>User role: {user.role}</TooltipContent>
                  </Tooltip>
                </Table.Cell>
                <Table.Cell>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge variant={user.isActive ? 'success' : 'neutral'} size="sm">
                        {user.isActive ? 'Active' : 'Inactive'}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent>{user.isActive ? 'User account is active' : 'User account is inactive'}</TooltipContent>
                  </Tooltip>
                </Table.Cell>
                <Table.Cell className="text-right">
                  {USER_MGMT_ENABLED ? (
                    <div className="flex items-center justify-end gap-2">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          {/* aria-label, not just a Tooltip: these are icon-only
                              buttons, so without it a screen reader announces
                              "button" with no indication of what it does or which
                              row it belongs to. axe flags it as button-name. */}
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`Edit ${user.name || user.email}`}
                            onClick={() => openEditModal(user)}
                          >
                            <Edit className="w-4 h-4" aria-hidden="true" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Modify user details and permissions</TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`Deactivate ${user.name || user.email}`}
                            onClick={() => handleDeleteUser(user.id)}
                          >
                            <Trash2 className="w-4 h-4 text-red-500" aria-hidden="true" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Deactivate this user — their history is kept</TooltipContent>
                      </Tooltip>
                    </div>
                  ) : (
                    <span className="text-opsgrid-text-secondary">—</span>
                  )}
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        {users && users.total > users.items.length && (
          <div className="flex items-center justify-between border-t border-opsgrid-border px-4 py-3 text-sm">
            <span className="text-opsgrid-text-secondary">
              Showing {users.items.length} of {users.total} users
            </span>
            {limit < MAX_PAGE ? (
              <Button
                variant="secondary"
                onClick={() => setLimit((n) => Math.min(n + PAGE_SIZE, MAX_PAGE))}
              >
                Show more
              </Button>
            ) : (
              // The server's ceiling, stated rather than hidden. Silently stopping here
              // is the exact failure this page was just fixed for.
              <span className="text-opsgrid-text-secondary">
                Showing the first {MAX_PAGE} — narrow the list from the admin API to see
                the rest.
              </span>
            )}
          </div>
        )}
      </Card>

      {/* Add User Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg max-w-md w-full">
            <div className="p-6 border-b border-opsgrid-border flex items-center justify-between">
              <h3 className="text-xl font-semibold">Add New User</h3>
              <button onClick={() => setShowAddModal(false)} className="text-opsgrid-text-secondary hover:text-opsgrid-text">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <Input
                label="Name"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="Enter user name"
              />
              <Input
                label="Email"
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                placeholder="Enter email address"
              />
              <Input
                label="Password"
                type="password"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                placeholder="Enter password"
              />
              <Select
                label="Role"
                value={formData.role}
                onChange={(e) => setFormData({ ...formData, role: e.target.value as UserRole })}
                options={[
                  { value: 'admin', label: 'Admin' },
                  { value: 'operator', label: 'Operator' },
                  { value: 'viewer', label: 'Viewer' },
                ]}
              />
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.isActive}
                  onChange={(e) => setFormData({ ...formData, isActive: e.target.checked })}
                  className="w-4 h-4 rounded border-opsgrid-border"
                />
                <span className="text-sm">Active</span>
              </label>
            </div>
            <div className="p-6 border-t border-opsgrid-border flex justify-end gap-3">
              <Button variant="secondary" onClick={() => setShowAddModal(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleAddUser}
                disabled={createMutation.isPending}
              >
                {createMutation.isPending ? 'Creating...' : 'Create User'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Edit User Modal */}
      {showEditModal && selectedUser && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg max-w-md w-full">
            <div className="p-6 border-b border-opsgrid-border flex items-center justify-between">
              <h3 className="text-xl font-semibold">Edit User</h3>
              <button onClick={() => setShowEditModal(false)} className="text-opsgrid-text-secondary hover:text-opsgrid-text">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <Input
                label="Name"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="Enter user name"
              />
              <Input
                label="Email"
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                placeholder="Enter email address"
              />
              <Select
                label="Role"
                value={formData.role}
                onChange={(e) => setFormData({ ...formData, role: e.target.value as UserRole })}
                options={[
                  { value: 'admin', label: 'Admin' },
                  { value: 'operator', label: 'Operator' },
                  { value: 'viewer', label: 'Viewer' },
                ]}
              />
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.isActive}
                  onChange={(e) => setFormData({ ...formData, isActive: e.target.checked })}
                  className="w-4 h-4 rounded border-opsgrid-border"
                />
                <span className="text-sm">Active</span>
              </label>
            </div>
            <div className="p-6 border-t border-opsgrid-border flex justify-end gap-3">
              <Button variant="secondary" onClick={() => setShowEditModal(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleEditUser}
                disabled={updateMutation.isPending}
              >
                {updateMutation.isPending ? 'Updating...' : 'Update User'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

interface EdgeAgent {
  agent_id: string;
  liveness: string;
  last_seen: string | null;
  buffer_pending: number;
  dead_lettered: number;
  active_collectors: number;
  total_collectors: number;
  cert_expires_in_seconds: number | null;
}

export const CollectorsPage: FC = () => {
  const { data: agents, isLoading, isError } = useQuery({
    queryKey: ['edge-fleet'],
    queryFn: async () => {
      const res = await api.get<EdgeAgent[]>('/api/v1/edge/fleet');
      return res.data;
    },
    refetchInterval: 30_000, // liveness must refresh, not freeze at mount
  });

  const livenessVariant = (l: string): 'success' | 'warning' | 'error' =>
    l === 'live' || l === 'online' ? 'success' : l === 'stale' ? 'warning' : 'error';

  return (
    <div className="space-y-6">
      <Card title="Edge Agents" subtitle="Live data-collection agents reporting via heartbeat">
        {isLoading ? (
          <SkeletonCard />
        ) : isError ? (
          /* The empty state below EXPLAINS itself — "agents appear here once they enroll
             and send a heartbeat" — which is a confident account of why the list is
             empty, and simply wrong when the request failed. On error `agents` is
             undefined, so `!agents` sent every failure straight into that sentence. */
          <p className="text-sm text-status-alarm" role="alert">
            Couldn’t load the agent fleet — this is a loading failure, not an empty fleet.
          </p>
        ) : !agents || agents.length === 0 ? (
          <p className="text-sm text-opsgrid-text-secondary">
            No edge agents have reported yet. Agents appear here once they enroll and send a heartbeat.
          </p>
        ) : (
          <div className="space-y-2">
            {agents.map((a) => (
              <Tooltip key={a.agent_id}>
                <TooltipTrigger asChild>
                  <div className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
                    <div className="flex items-center gap-3">
                      <HardDrive className="text-opsgrid-primary" size={20} />
                      <div>
                        <p className="font-medium">{a.agent_id}</p>
                        <p className="text-sm text-opsgrid-text-secondary">
                          {a.active_collectors}/{a.total_collectors} collectors
                          {a.buffer_pending > 0 && ` • ${a.buffer_pending} buffered`}
                          {a.dead_lettered > 0 && ` • ${a.dead_lettered} dead-lettered`}
                        </p>
                      </div>
                    </div>
                    <Badge variant={livenessVariant(a.liveness)} size="sm">{a.liveness}</Badge>
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  Last seen: {a.last_seen ? new Date(a.last_seen).toLocaleString() : 'never'}
                  {a.cert_expires_in_seconds != null &&
                    ` • cert expires in ${Math.round(a.cert_expires_in_seconds / 86400)}d`}
                </TooltipContent>
              </Tooltip>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};

export const SystemHealthPage: FC = () => {
  const { data: health } = useQuery({
    queryKey: ['health-detailed'],
    queryFn: async () => {
      const res = await api.get<{ status: string; checks: Record<string, string> }>('/health/detailed');
      return res.data;
    },
    refetchInterval: 15000,
  });
  const { data: sys } = useQuery({
    queryKey: ['health-system'],
    queryFn: async () => {
      const res = await api.get<{ available: boolean; cpu_percent: number | null; memory_percent: number | null; disk_percent: number | null }>('/health/system');
      return res.data;
    },
    refetchInterval: 15000,
  });

  const checks = health?.checks ?? {};
  const healthy = (s: string) => s === 'healthy' || s === 'ok' || s === 'up' || s === 'ready';
  const label = (k: string) => k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v)}%`);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {Object.entries(checks).map(([name, status]) => (
          <Tooltip key={name}>
            <TooltipTrigger asChild>
              <Card className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Activity className="w-5 h-5 text-opsgrid-primary" />
                    <span className="font-medium">{label(name)}</span>
                  </div>
                  <Badge variant={healthy(status) ? 'success' : 'error'} size="sm">{status}</Badge>
                </div>
              </Card>
            </TooltipTrigger>
            <TooltipContent>{label(name)} status: {status}</TooltipContent>
          </Tooltip>
        ))}
        {Object.keys(checks).length === 0 && (
          <p className="text-sm text-opsgrid-text-secondary">Loading component health…</p>
        )}
      </div>

      <Card title="System Metrics" subtitle={sys?.available ? 'Live host resource utilization' : 'Host metrics unavailable'}>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {[
            { label: 'CPU', value: pct(sys?.cpu_percent) },
            { label: 'Memory', value: pct(sys?.memory_percent) },
            { label: 'Disk', value: pct(sys?.disk_percent) },
          ].map((metric) => (
            <div key={metric.label} className="p-3 bg-opsgrid-bg rounded-lg text-center">
              <p className="text-xl font-bold">{metric.value}</p>
              <p className="text-sm text-opsgrid-text-secondary">{metric.label}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};

// camelCase: /api/v1/organizations is registered with the transform seam
// (src/api/assets.ts), which camelizes responses and snake_cases the PUT body.
interface OrgSettings {
  timezone?: string;
  dateFormat?: string;
  notifyEmail?: boolean;
  notifySms?: boolean;
  notifyWebhook?: boolean;
}

const SETTING_DEFAULTS: Required<OrgSettings> = {
  timezone: 'America/Chicago',
  dateFormat: 'MM/dd/yyyy',
  notifyEmail: true,
  notifySms: true,
  notifyWebhook: true,
};

export const SettingsPage: FC = () => {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({
    queryKey: ['org-settings'],
    queryFn: async () => {
      const res = await api.get<OrgSettings>('/api/v1/organizations/settings/current');
      return res.data;
    },
  });

  const [draft, setDraft] = useState<OrgSettings>({});
  // Explicit defaults first, stored values over them, unsaved edits on top.
  const current = { ...SETTING_DEFAULTS, ...settings, ...draft };

  const save = useMutation({
    // Send only the edited keys: the server merges, and re-sending the full
    // snapshot would clobber concurrent edits from another admin/tab.
    mutationFn: (patch: OrgSettings) => api.put('/api/v1/organizations/settings/current', patch),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['org-settings'] }); setDraft({}); },
  });

  const set = (key: keyof OrgSettings, value: any) => setDraft((d) => ({ ...d, [key]: value }));
  const dirty = Object.keys(draft).length > 0;

  return (
    <div className="space-y-6">
      <Card title="General Settings" subtitle="Organization preferences">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Input
            label="Timezone"
            value={current.timezone}
            onChange={(e) => set('timezone', e.target.value)}
          />
          <Select
            label="Date Format"
            value={current.dateFormat}
            onChange={(e) => set('dateFormat', e.target.value)}
            options={[
              { value: 'MM/dd/yyyy', label: 'MM/DD/YYYY' },
              { value: 'dd/MM/yyyy', label: 'DD/MM/YYYY' },
              { value: 'yyyy-MM-dd', label: 'YYYY-MM-DD' },
            ]}
          />
        </div>
      </Card>

      <Card title="Notifications" subtitle="Alert preferences">
        <div className="space-y-3">
          {([
            ['notifyEmail', 'Email alerts'],
            ['notifySms', 'SMS notifications'],
            ['notifyWebhook', 'Webhook events'],
          ] as [keyof OrgSettings, string][]).map(([key, label]) => (
            <label key={key} className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                className="w-4 h-4 rounded border-opsgrid-border"
                checked={Boolean(current[key])}
                onChange={(e) => set(key, e.target.checked)}
              />
              <span className="text-sm">{label}</span>
            </label>
          ))}
        </div>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={() => save.mutate(draft)} disabled={!dirty || save.isPending}>
          {save.isPending ? 'Saving…' : 'Save changes'}
        </Button>
        {save.isSuccess && !dirty && <span className="text-sm text-status-success">Saved</span>}
      </div>
    </div>
  );
};
