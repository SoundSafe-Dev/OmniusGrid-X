import { Fragment, useState, useEffect } from 'react';
import { Shield, Search, Download, AlertTriangle, CheckCircle } from 'lucide-react';
import { Card, Button, Input, Select, Table, Badge } from '../../components/ui';

interface AuditLog {
  id: string;
  timestamp: string;
  user_id: string;
  organization_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  details: unknown;
  ip_address: string;
  user_agent: string;
  hash_chain: string;
}

interface AuditLogsResponse {
  items: AuditLog[];
  total: number;
  skip: number;
  limit: number;
}

const ACTION_OPTIONS = [
  { value: '', label: 'All actions' },
  { value: 'user_created', label: 'User Created' },
  { value: 'user_deleted', label: 'User Deleted' },
  { value: 'asset_updated', label: 'Asset Updated' },
  { value: 'command_executed', label: 'Command Executed' },
  { value: 'task_approved', label: 'Task Approved' },
  { value: 'task_rejected', label: 'Task Rejected' },
];

const RESOURCE_TYPE_OPTIONS = [
  { value: '', label: 'All types' },
  { value: 'user', label: 'User' },
  { value: 'asset', label: 'Asset' },
  { value: 'command', label: 'Command' },
  { value: 'kanban_task', label: 'Kanban Task' },
  { value: 'registry_item', label: 'Registry Item' },
];

export default function AuditLogs() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const [hashChainStatus, setHashChainStatus] = useState<{ verified: boolean; message: string } | null>(null);

  // Filters
  const [actionFilter, setActionFilter] = useState<string>('');
  const [resourceTypeFilter, setResourceTypeFilter] = useState<string>('');
  const [dateFrom, setDateFrom] = useState<string>('');
  const [dateTo, setDateTo] = useState<string>('');
  const [searchTerm, setSearchTerm] = useState<string>('');

  // Pagination
  const [skip, setSkip] = useState(0);
  const [limit] = useState(50);
  const [total, setTotal] = useState(0);

  const fetchLogs = async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({
        skip: skip.toString(),
        limit: limit.toString(),
      });

      if (actionFilter) params.append('action', actionFilter);
      if (resourceTypeFilter) params.append('resource_type', resourceTypeFilter);
      if (dateFrom) params.append('start_time', dateFrom);
      if (dateTo) params.append('end_time', dateTo);

      const token = localStorage.getItem('accessToken') || localStorage.getItem('devToken');
      const response = await fetch(`/api/v1/audit/logs?${params}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch audit logs');
      }

      const data: AuditLogsResponse = await response.json();
      setLogs(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  const verifyHashChain = async () => {
    try {
      const token = localStorage.getItem('accessToken') || localStorage.getItem('devToken');
      const response = await fetch('/api/v1/audit/verify', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to verify hash chain');
      }

      const data = await response.json();
      setHashChainStatus(data);
    } catch (err) {
      setHashChainStatus({
        verified: false,
        message: err instanceof Error ? err.message : 'Verification failed',
      });
    }
  };

  const exportLogs = () => {
    const csv = [
      ['Timestamp', 'User ID', 'Action', 'Resource Type', 'Resource ID', 'IP Address'],
      ...logs.map(log => [
        log.timestamp,
        log.user_id,
        log.action,
        log.resource_type || '',
        log.resource_id || '',
        log.ip_address || '',
      ]),
    ].map(row => row.join(',')).join('\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit-logs-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
  };

  useEffect(() => {
    fetchLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skip, actionFilter, resourceTypeFilter, dateFrom, dateTo]);

  const filteredLogs = logs.filter(log =>
    log.action?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    log.resource_type?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    log.user_id?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-opsgrid-text flex items-center gap-2">
            <Shield className="w-8 h-8" />
            Audit Logs
          </h1>
          <p className="text-opsgrid-text-secondary mt-1">
            Security audit trail for sensitive operations
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={verifyHashChain} variant="outline">
            <CheckCircle className="w-4 h-4 mr-2" />
            Verify Hash Chain
          </Button>
          <Button onClick={exportLogs} variant="outline">
            <Download className="w-4 h-4 mr-2" />
            Export CSV
          </Button>
        </div>
      </div>

      {hashChainStatus && (
        <Card className={hashChainStatus.verified ? 'border-status-running' : 'border-status-alarm'}>
          <div className="flex items-center gap-2">
            {hashChainStatus.verified ? (
              <CheckCircle className="w-5 h-5 text-status-running" />
            ) : (
              <AlertTriangle className="w-5 h-5 text-status-alarm" />
            )}
            <span className="font-medium text-opsgrid-text">{hashChainStatus.message}</span>
          </div>
        </Card>
      )}

      <Card title="Filters">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="relative">
            <Input
              label="Search"
              placeholder="Search logs..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10"
            />
            <Search className="absolute left-3 bottom-3 w-4 h-4 text-opsgrid-text-secondary pointer-events-none" />
          </div>
          <Select
            label="Action"
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            options={ACTION_OPTIONS}
          />
          <Select
            label="Resource Type"
            value={resourceTypeFilter}
            onChange={(e) => setResourceTypeFilter(e.target.value)}
            options={RESOURCE_TYPE_OPTIONS}
          />
          <div>
            <label className="block text-sm font-medium text-opsgrid-text mb-1">Date Range</label>
            <div className="flex gap-2">
              <Input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
              />
              <Input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </div>
          </div>
        </div>
      </Card>

      <Card title={`Audit Log Entries (${filteredLogs.length} of ${total})`} noPadding>
        {loading ? (
          <div className="text-center py-8 text-opsgrid-text-secondary">Loading...</div>
        ) : error ? (
          <div className="text-center py-8 text-status-alarm">{error}</div>
        ) : (
          <Table>
            <Table.Head>
              <Table.Row>
                <Table.Header>Timestamp</Table.Header>
                <Table.Header>Action</Table.Header>
                <Table.Header>Resource Type</Table.Header>
                <Table.Header>Resource ID</Table.Header>
                <Table.Header>User ID</Table.Header>
                <Table.Header>IP Address</Table.Header>
                <Table.Header>Actions</Table.Header>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {filteredLogs.map((log) => (
                <Fragment key={log.id}>
                  <Table.Row key={log.id}>
                    <Table.Cell className="font-mono text-sm">
                      {new Date(log.timestamp).toLocaleString()}
                    </Table.Cell>
                    <Table.Cell>
                      <Badge variant="neutral">{log.action}</Badge>
                    </Table.Cell>
                    <Table.Cell>{log.resource_type || '-'}</Table.Cell>
                    <Table.Cell className="font-mono text-sm">
                      {log.resource_id ? log.resource_id.slice(0, 8) + '...' : '-'}
                    </Table.Cell>
                    <Table.Cell className="font-mono text-sm">
                      {log.user_id ? log.user_id.slice(0, 8) + '...' : '-'}
                    </Table.Cell>
                    <Table.Cell className="font-mono text-sm">
                      {log.ip_address || '-'}
                    </Table.Cell>
                    <Table.Cell>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setExpandedLogId(expandedLogId === log.id ? null : log.id)}
                      >
                        {expandedLogId === log.id ? 'Hide Details' : 'View Details'}
                      </Button>
                    </Table.Cell>
                  </Table.Row>
                  {expandedLogId === log.id && (
                    <Table.Row key={`${log.id}-details`}>
                      <Table.Cell colSpan={7} className="bg-opsgrid-bg">
                        <div className="p-4 space-y-4">
                          <div className="grid grid-cols-2 gap-4">
                            <div>
                              <p className="text-sm font-medium text-opsgrid-text-secondary">ID</p>
                              <p className="font-mono text-sm">{log.id}</p>
                            </div>
                            <div>
                              <p className="text-sm font-medium text-opsgrid-text-secondary">Timestamp</p>
                              <p className="font-mono text-sm">{log.timestamp}</p>
                            </div>
                            <div>
                              <p className="text-sm font-medium text-opsgrid-text-secondary">Action</p>
                              <p><Badge variant="neutral">{log.action}</Badge></p>
                            </div>
                            <div>
                              <p className="text-sm font-medium text-opsgrid-text-secondary">Resource Type</p>
                              <p>{log.resource_type || '-'}</p>
                            </div>
                            <div>
                              <p className="text-sm font-medium text-opsgrid-text-secondary">Resource ID</p>
                              <p className="font-mono text-sm">{log.resource_id || '-'}</p>
                            </div>
                            <div>
                              <p className="text-sm font-medium text-opsgrid-text-secondary">User ID</p>
                              <p className="font-mono text-sm">{log.user_id || '-'}</p>
                            </div>
                            <div>
                              <p className="text-sm font-medium text-opsgrid-text-secondary">Organization ID</p>
                              <p className="font-mono text-sm">{log.organization_id || '-'}</p>
                            </div>
                            <div>
                              <p className="text-sm font-medium text-opsgrid-text-secondary">IP Address</p>
                              <p className="font-mono text-sm">{log.ip_address || '-'}</p>
                            </div>
                          </div>
                          <div>
                            <p className="text-sm font-medium text-opsgrid-text-secondary">User Agent</p>
                            <p className="text-sm text-opsgrid-text-secondary break-all">
                              {log.user_agent || '-'}
                            </p>
                          </div>
                          <div>
                            <p className="text-sm font-medium text-opsgrid-text-secondary">Hash Chain</p>
                            <p className="font-mono text-sm break-all">{log.hash_chain}</p>
                          </div>
                          <div>
                            <p className="text-sm font-medium text-opsgrid-text-secondary">Details</p>
                            <pre className="bg-opsgrid-panel p-4 rounded-md text-xs overflow-x-auto">
                              {JSON.stringify(log.details, null, 2)}
                            </pre>
                          </div>
                        </div>
                      </Table.Cell>
                    </Table.Row>
                  )}
                </Fragment>
              ))}
            </Table.Body>
          </Table>
        )}

        {total > limit && (
          <div className="flex items-center justify-between p-4 border-t border-opsgrid-border">
            <p className="text-sm text-opsgrid-text-secondary">
              Showing {skip + 1} to {Math.min(skip + limit, total)} of {total}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setSkip(Math.max(0, skip - limit))}
                disabled={skip === 0}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setSkip(skip + limit)}
                disabled={skip + limit >= total}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
