import { FC, useState } from 'react';
import { useQuery } from 'react-query';
import { Users, Settings, Activity, HardDrive } from 'lucide-react';
import { Card, Badge, Button, Table, SkeletonCard, Input, Select } from '../../components';
import { authApi } from '../../api';
import { User, UserRole } from '../../types';

export const UsersPage: FC = () => {
  const { data: users, isLoading } = useQuery('users', () => authApi.getUsers());

  if (isLoading) return <SkeletonCard lines={5} />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">User Management</h2>
        <Button variant="primary">Add User</Button>
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
                  <Badge variant="info" size="sm">{user.role}</Badge>
                </Table.Cell>
                <Table.Cell>
                  <Badge variant={user.isActive ? 'success' : 'neutral'} size="sm">
                    {user.isActive ? 'Active' : 'Inactive'}
                  </Badge>
                </Table.Cell>
                <Table.Cell className="text-right">
                  <Button variant="ghost" size="sm">Edit</Button>
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
      </Card>
    </div>
  );
};

export const CollectorsPage: FC = () => {
  return (
    <div className="space-y-6">
      <Card title="Data Collectors" subtitle="Edge data collection agents">
        <div className="space-y-2">
          {['MQTT Collector (Bambu)', 'OPC-UA Collector', 'Screen Scraper'].map((collector) => (
            <div key={collector} className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
              <div className="flex items-center gap-3">
                <HardDrive className="text-opsgrid-primary" size={20} />
                <div>
                  <p className="font-medium">{collector}</p>
                  <p className="text-sm text-opsgrid-text-secondary">Running • 2.4.1</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="success" size="sm">Online</Badge>
                <Button variant="ghost" size="sm">Restart</Button>
              </div>
            </div>
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
          <Card key={service.name} className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <service.icon className="w-5 h-5 text-opsgrid-primary" />
                <span className="font-medium">{service.name}</span>
              </div>
              <Badge variant="success" size="sm">{service.status}</Badge>
            </div>
          </Card>
        ))}
      </div>

      <Card title="System Metrics" subtitle="Resource utilization">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'CPU', value: '24%' },
            { label: 'Memory', value: '45%' },
            { label: 'Disk', value: '32%' },
            { label: 'Network', value: '12 Mbps' },
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
