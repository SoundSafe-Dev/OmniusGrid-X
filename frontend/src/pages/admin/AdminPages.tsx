import { FC, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from 'react-query';
import { Users, Settings, Activity, HardDrive, X, Plus, Edit, Trash2 } from 'lucide-react';
import { Card, Badge, Button, Table, SkeletonCard, Input, Select } from '../../components';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';
import { authApi } from '../../api';
import { User, UserRole } from '../../types';

export const UsersPage: FC = () => {
  const queryClient = useQueryClient();
  const { data: users, isLoading } = useQuery('users', () => authApi.getUsers());
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

  const createMutation = useMutation(
    (userData: typeof formData) => authApi.createUser(userData),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('users');
        setShowAddModal(false);
        setFormData({ name: '', email: '', role: 'viewer', isActive: true, password: '' });
      },
    }
  );

  const updateMutation = useMutation(
    ({ userId, userData }: { userId: string; userData: Partial<User> }) =>
      authApi.updateUser(userId, userData),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('users');
        setShowEditModal(false);
        setSelectedUser(null);
      },
    }
  );

  const deleteMutation = useMutation(
    (userId: string) => authApi.deleteUser(userId),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('users');
      },
    }
  );

  const handleAddUser = () => {
    if (!formData.name || !formData.email || !formData.password) {
      alert('Please fill in all required fields');
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

  const handleDeleteUser = (userId: string) => {
    if (confirm('Are you sure you want to delete this user?')) {
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">User Management</h2>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="primary" onClick={() => setShowAddModal(true)}>
              <Plus className="w-4 h-4 mr-2" />
              Add User
            </Button>
          </TooltipTrigger>
          <TooltipContent>Create a new user account</TooltipContent>
        </Tooltip>
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
                disabled={createMutation.isLoading}
              >
                {createMutation.isLoading ? 'Creating...' : 'Create User'}
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
                disabled={updateMutation.isLoading}
              >
                {updateMutation.isLoading ? 'Updating...' : 'Update User'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export const CollectorsPage: FC = () => {
  return (
    <div className="space-y-6">
      <Card title="Data Collectors" subtitle="Edge data collection agents">
        <div className="space-y-2">
          {['MQTT Collector (Bambu)', 'OPC-UA Collector', 'Screen Scraper'].map((collector) => (
            <Tooltip key={collector}>
              <TooltipTrigger asChild>
                <div className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
                  <div className="flex items-center gap-3">
                    <HardDrive className="text-opsgrid-primary" size={20} />
                    <div>
                      <p className="font-medium">{collector}</p>
                      <p className="text-sm text-opsgrid-text-secondary">Running • 2.4.1</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Badge variant="success" size="sm">Online</Badge>
                      </TooltipTrigger>
                      <TooltipContent>Collector is running and connected</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button variant="ghost" size="sm">Restart</Button>
                      </TooltipTrigger>
                      <TooltipContent>Restart collector service</TooltipContent>
                    </Tooltip>
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent>Collector is currently offline</TooltipContent>
            </Tooltip>
          ))}
        </div>
      </Card>
    </div>
  );
};

export const SystemHealthPage: FC = () => {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { name: 'API Server', status: 'healthy', icon: Activity },
          { name: 'Database', status: 'healthy', icon: HardDrive },
          { name: 'Message Queue', status: 'healthy', icon: Activity },
        ].map((service) => (
          <Tooltip key={service.name}>
            <TooltipTrigger asChild>
              <Card className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <service.icon className="w-5 h-5 text-opsgrid-primary" />
                    <span className="font-medium">{service.name}</span>
                  </div>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge variant="success" size="sm">{service.status}</Badge>
                    </TooltipTrigger>
                    <TooltipContent>Service is operational</TooltipContent>
                  </Tooltip>
                </div>
              </Card>
            </TooltipTrigger>
            <TooltipContent>
              <div className="space-y-1">
                <p className="font-medium">{service.name}</p>
                <p className="text-xs text-opsgrid-text-secondary">Infrastructure service</p>
                <p className="text-xs">Status: {service.status}</p>
              </div>
            </TooltipContent>
          </Tooltip>
        ))}
      </div>

      <Card title="System Metrics" subtitle="Resource utilization">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'CPU', value: '24%', description: 'Processor utilization' },
            { label: 'Memory', value: '45%', description: 'RAM usage' },
            { label: 'Disk', value: '32%', description: 'Storage usage' },
            { label: 'Network', value: '12 Mbps', description: 'Network throughput' },
          ].map((metric) => (
            <Tooltip key={metric.label}>
              <TooltipTrigger asChild>
                <div className="p-3 bg-opsgrid-bg rounded-lg text-center">
                  <p className="text-xl font-bold">{metric.value}</p>
                  <p className="text-sm text-opsgrid-text-secondary">{metric.label}</p>
                </div>
              </TooltipTrigger>
              <TooltipContent>
                <div className="space-y-1">
                  <p className="font-medium">{metric.label}</p>
                  <p className="text-xs text-opsgrid-text-secondary">{metric.description}</p>
                  <p className="text-xs">Current: {metric.value}</p>
                </div>
              </TooltipContent>
            </Tooltip>
          ))}
        </div>
      </Card>
    </div>
  );
};

export const SettingsPage: FC = () => {
  return (
    <div className="space-y-6">
      <Card title="General Settings" subtitle="Application preferences">
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Input label="Timezone" value="America/Chicago" readOnly />
            <Select
              label="Date Format"
              value="MM/dd/yyyy"
              options={[
                { value: 'MM/dd/yyyy', label: 'MM/DD/YYYY' },
                { value: 'dd/MM/yyyy', label: 'DD/MM/YYYY' },
                { value: 'yyyy-MM-dd', label: 'YYYY-MM-DD' },
              ]}
            />
          </div>
        </div>
      </Card>

      <Card title="Notifications" subtitle="Alert preferences">
        <div className="space-y-3">
          {['Email alerts', 'SMS notifications', 'Webhook events'].map((setting) => (
            <label key={setting} className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" className="w-4 h-4 rounded border-opsgrid-border" defaultChecked />
              <span className="text-sm">{setting}</span>
            </label>
          ))}
        </div>
      </Card>
    </div>
  );
};
