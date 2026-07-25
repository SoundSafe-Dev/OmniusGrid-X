import { FC, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Activity, HardDrive, X, Plus, Edit, Trash2 } from 'lucide-react';
import { Card, Badge, Button, Table, SkeletonCard, Input, Select } from '../../components';
import { Tooltip, TooltipTrigger, TooltipContent, useDialog } from '../../components/ui';
import { authApi, api } from '../../api';
import { User, UserRole } from '../../types';

export const UsersPage: FC = () => {
  const queryClient = useQueryClient();
  const { confirm, alert } = useDialog();
  const { data: users, isLoading, isError } = useQuery({ queryKey: ['users'], queryFn: () => authApi.getUsers() });
  // The backend exposes GET /users but no POST/PUT/DELETE /users routes yet, so
  // create/edit/delete would 404. Hide those write affordances until the
  // endpoints land (flip to true then) instead of shipping dead buttons.
  const USER_MGMT_ENABLED = false;
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
    const ok = await confirm({
      title: 'Delete user',
      message: 'Are you sure you want to delete this user? This cannot be undone.',
      confirmLabel: 'Delete',
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
                          <Button variant="ghost" size="sm" onClick={() => openEditModal(user)}>
                            <Edit className="w-4 h-4" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Modify user details and permissions</TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="ghost" size="sm" onClick={() => handleDeleteUser(user.id)}>
                            <Trash2 className="w-4 h-4 text-red-500" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Delete this user account</TooltipContent>
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
  const { data: agents, isLoading } = useQuery({
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
