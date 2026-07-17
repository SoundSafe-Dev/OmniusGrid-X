import { FC } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Cloud, Upload, Wifi, Shield, Clock } from 'lucide-react';
import { Card, Badge, Button, SkeletonCard } from '../../components';
import { enginesApi } from '../../api';
import { formatBytes, formatDateTime, formatDuration } from '../../utils';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';

export const CloudGateway: FC = () => {
  const queryClient = useQueryClient();

  const { data: status, isLoading } = useQuery({
    queryKey: ['cloud-gateway-status'],
    queryFn: () => enginesApi.getCloudGatewayStatus(),
    refetchInterval: 10000,
  });

  const flushMutation = useMutation({
    mutationFn: () => enginesApi.forceCloudFlush(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cloud-gateway-status'] }),
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={6} />
      </div>
    );
  }

  const isConnected = status?.connected || false;
  const egress = status?.egressStats;

  return (
    <div className="space-y-6">
      {/* Connection Status */}
      <Card className="p-6">
        <div className="flex items-center justify-between">
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-4">
                <div className={`p-4 rounded-xl ${isConnected ? 'bg-status-running/20' : 'bg-status-offline/20'}`}>
                  {isConnected ? (
                    <Cloud className="w-10 h-10 text-status-running" />
                  ) : (
                    <Cloud className="w-10 h-10 text-status-offline" />
                  )}
                </div>
                <div>
                  <h2 className="text-2xl font-bold">{isConnected ? 'Connected' : 'Disconnected'}</h2>
                  <p className="text-opsgrid-text-secondary">
                    {isConnected
                      ? `Last sync: ${status?.lastSyncAt ? formatDateTime(status.lastSyncAt) : 'Never'}`
                      : status?.lastDisconnectedAt
                      ? `Disconnected at: ${formatDateTime(status.lastDisconnectedAt)}`
                      : 'Connection status unknown'}
                  </p>
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent>Cloud gateway connection status and sync information</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant={isConnected ? 'success' : 'error'} size="md">
                {isConnected ? 'Online' : 'Offline'}
              </Badge>
            </TooltipTrigger>
            <TooltipContent>{isConnected ? 'Gateway is connected to cloud' : 'Gateway is disconnected from cloud'}</TooltipContent>
          </Tooltip>
        </div>
      </Card>

      {/* Quick Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Upload className="w-5 h-5 text-opsgrid-primary" />
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Data Sent</p>
                  <p className="font-medium">{egress ? formatBytes(egress.totalBytesSent) : '—'}</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Total data sent to cloud</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Shield className="w-5 h-5 text-opsgrid-primary" />
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Compression</p>
                  <p className="font-medium">
                    {egress ? `${(egress.compressionRatio * 100).toFixed(0)}%` : '—'}
                  </p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Data compression ratio</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Wifi className="w-5 h-5 text-opsgrid-primary" />
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Bandwidth</p>
                  <p className="font-medium">
                    {egress ? `${egress.averageBandwidthKbps.toFixed(1)} Kbps` : '—'}
                  </p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Average bandwidth usage</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Clock className="w-5 h-5 text-opsgrid-primary" />
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Queue Depth</p>
                  <p className="font-medium">{egress?.queueDepth || 0} items</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Number of items in upload queue</TooltipContent>
        </Tooltip>
      </div>

      {/* Flush Controls */}
      <Card title="Data Flush" subtitle="Force immediate sync to cloud">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center justify-between p-4 bg-opsgrid-bg rounded-lg">
              <div>
                <p className="font-medium">Manual Flush</p>
                <p className="text-sm text-opsgrid-text-secondary">
                  Immediately send all queued data to the cloud
                </p>
              </div>
              <Button
                variant="primary"
                disabled={!isConnected || flushMutation.isPending}
                loading={flushMutation.isPending}
                onClick={() => flushMutation.mutate()}
              >
                <Upload size={16} className="mr-1" />
                Flush Now
              </Button>
            </div>
          </TooltipTrigger>
          <TooltipContent>Force immediate data sync to cloud</TooltipContent>
        </Tooltip>
      </Card>

      {/* Security Info */}
      <Card title="Security" subtitle="Connection encryption details">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="p-4 bg-opsgrid-bg rounded-lg">
            <div className="flex items-center gap-3 mb-2">
              <Shield className="w-5 h-5 text-status-running" />
              <p className="font-medium">mTLS Enabled</p>
            </div>
            <p className="text-sm text-opsgrid-text-secondary">
              Mutual TLS authentication ensures secure bidirectional communication
            </p>
          </div>

          <div className="p-4 bg-opsgrid-bg rounded-lg">
            <p className="text-sm text-opsgrid-text-secondary mb-1">Certificate Expiry</p>
            <p className="font-medium">
              {status?.mTlsCertificateExpiry
                ? formatDateTime(status.mTlsCertificateExpiry)
                : 'Unknown'}
            </p>
          </div>
        </div>
      </Card>

      {/* Uptime */}
      {status?.connectionUptimeSeconds !== undefined && (
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Wifi className="w-5 h-5 text-opsgrid-primary" />
              <span className="font-medium">Connection Uptime</span>
            </div>
            <span className="text-opsgrid-text-secondary">
              {formatDuration(status.connectionUptimeSeconds)}
            </span>
          </div>
        </Card>
      )}
    </div>
  );
};
