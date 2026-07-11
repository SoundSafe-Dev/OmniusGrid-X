import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Shield, Search, Download, AlertTriangle, CheckCircle } from 'lucide-react';

interface AuditLog {
  id: string;
  timestamp: string;
  user_id: string;
  organization_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  details: any;
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
  }, [skip, actionFilter, resourceTypeFilter, dateFrom, dateTo]);

  const filteredLogs = logs.filter(log =>
    log.action.toLowerCase().includes(searchTerm.toLowerCase()) ||
    log.resource_type?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    log.user_id?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Shield className="w-8 h-8" />
            Audit Logs
          </h1>
          <p className="text-muted-foreground mt-1">
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
        <Card className={hashChainStatus.verified ? 'border-green-500' : 'border-red-500'}>
          <CardContent className="pt-6">
            <div className="flex items-center gap-2">
              {hashChainStatus.verified ? (
                <CheckCircle className="w-5 h-5 text-green-500" />
              ) : (
                <AlertTriangle className="w-5 h-5 text-red-500" />
              )}
              <span className="font-medium">{hashChainStatus.message}</span>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Search</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="Search logs..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-10"
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Action</label>
              <Select value={actionFilter} onValueChange={setActionFilter}>
                <SelectTrigger>
                  <SelectValue placeholder="All actions" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All actions</SelectItem>
                  <SelectItem value="user_created">User Created</SelectItem>
                  <SelectItem value="user_deleted">User Deleted</SelectItem>
                  <SelectItem value="asset_updated">Asset Updated</SelectItem>
                  <SelectItem value="command_executed">Command Executed</SelectItem>
                  <SelectItem value="task_approved">Task Approved</SelectItem>
                  <SelectItem value="task_rejected">Task Rejected</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Resource Type</label>
              <Select value={resourceTypeFilter} onValueChange={setResourceTypeFilter}>
                <SelectTrigger>
                  <SelectValue placeholder="All types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All types</SelectItem>
                  <SelectItem value="user">User</SelectItem>
                  <SelectItem value="asset">Asset</SelectItem>
                  <SelectItem value="command">Command</SelectItem>
                  <SelectItem value="kanban_task">Kanban Task</SelectItem>
                  <SelectItem value="registry_item">Registry Item</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Date Range</label>
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
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            Audit Log Entries ({filteredLogs.length} of {total})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-center py-8">Loading...</div>
          ) : error ? (
            <div className="text-center py-8 text-red-500">{error}</div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Timestamp</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Resource Type</TableHead>
                    <TableHead>Resource ID</TableHead>
                    <TableHead>User ID</TableHead>
                    <TableHead>IP Address</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredLogs.map((log) => (
                    <>
                      <TableRow key={log.id}>
                        <TableCell className="font-mono text-sm">
                          {new Date(log.timestamp).toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{log.action}</Badge>
                        </TableCell>
                        <TableCell>{log.resource_type || '-'}</TableCell>
                        <TableCell className="font-mono text-sm">
                          {log.resource_id ? log.resource_id.slice(0, 8) + '...' : '-'}
                        </TableCell>
                        <TableCell className="font-mono text-sm">
                          {log.user_id ? log.user_id.slice(0, 8) + '...' : '-'}
                        </TableCell>
                        <TableCell className="font-mono text-sm">
                          {log.ip_address || '-'}
                        </TableCell>
                        <TableCell>
                          <Button 
                            variant="ghost" 
                            size="sm"
                            onClick={() => setExpandedLogId(expandedLogId === log.id ? null : log.id)}
                          >
                            {expandedLogId === log.id ? 'Hide Details' : 'View Details'}
                          </Button>
                        </TableCell>
                      </TableRow>
                      {expandedLogId === log.id && (
                        <TableRow key={`${log.id}-details`}>
                          <TableCell colSpan={7} className="bg-muted">
                            <div className="p-4 space-y-4">
                              <div className="grid grid-cols-2 gap-4">
                                <div>
                                  <label className="text-sm font-medium">ID</label>
                                  <p className="font-mono text-sm">{log.id}</p>
                                </div>
                                <div>
                                  <label className="text-sm font-medium">Timestamp</label>
                                  <p className="font-mono text-sm">{log.timestamp}</p>
                                </div>
                                <div>
                                  <label className="text-sm font-medium">Action</label>
                                  <p><Badge variant="outline">{log.action}</Badge></p>
                                </div>
                                <div>
                                  <label className="text-sm font-medium">Resource Type</label>
                                  <p>{log.resource_type || '-'}</p>
                                </div>
                                <div>
                                  <label className="text-sm font-medium">Resource ID</label>
                                  <p className="font-mono text-sm">{log.resource_id || '-'}</p>
                                </div>
                                <div>
                                  <label className="text-sm font-medium">User ID</label>
                                  <p className="font-mono text-sm">{log.user_id || '-'}</p>
                                </div>
                                <div>
                                  <label className="text-sm font-medium">Organization ID</label>
                                  <p className="font-mono text-sm">{log.organization_id || '-'}</p>
                                </div>
                                <div>
                                  <label className="text-sm font-medium">IP Address</label>
                                  <p className="font-mono text-sm">{log.ip_address || '-'}</p>
                                </div>
                              </div>
                              <div>
                                <label className="text-sm font-medium">User Agent</label>
                                <p className="text-sm text-muted-foreground break-all">
                                  {log.user_agent || '-'}
                                </p>
                              </div>
                              <div>
                                <label className="text-sm font-medium">Hash Chain</label>
                                <p className="font-mono text-sm">{log.hash_chain}</p>
                              </div>
                              <div>
                                <label className="text-sm font-medium">Details</label>
                                <pre className="bg-background p-4 rounded-md text-xs overflow-x-auto">
                                  {JSON.stringify(log.details, null, 2)}
                                </pre>
                              </div>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          
          {total > limit && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-muted-foreground">
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
        </CardContent>
      </Card>
    </div>
  );
}
