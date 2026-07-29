import { FC } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Cloud, Upload, Shield, Clock, Server } from 'lucide-react';
import { Card, Badge, Button, SkeletonCard } from '../../components';
import { enginesApi } from '../../api';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';

// The backend `/cloud/status` (cloud_gateway.get_stats) returns only these
// fields — connection flag, queue size, endpoint host and the mTLS flag.
// Anything else (egress totals, compression, bandwidth, cert expiry, uptime)
// is not sent, so we render strictly from what actually arrives.
interface CloudStatus {
  connected: boolean;
  queueSize: number;
  endpoint: string;
  mtlsEnabled: boolean;
}

export const CloudGateway: FC = () => {
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
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

  const status = data as unknown as CloudStatus | undefined;
  // EVERY FIELD BELOW USED TO READ AS A FACT WHEN THERE WAS NO STATUS AT ALL. The error
  // banner rendered, and then the page went on to state — in full sentences, with red
  // icons — that the gateway was Disconnected and Offline, that the queue held 0 items,
  // and that "Mutual TLS is not enabled on this gateway connection". All four came from
  // `undefined` via `?? 0`, `|| false` and a falsy ternary. The queue depth is the
  // operational danger (nothing stranded at the edge) and the mTLS line is the sharper
  // one: it is a security claim about a link nobody managed to inspect.
  //
  // `known` is the whole fix. A failed status query means the STATUS is unreadable, not
  // that the gateway is down — those are different events with different responses.
  const known = status !== undefined;
  const isConnected = status?.connected ?? false;

  return (
    <div className="space-y-6">
      {isError && (
        <Card className="p-4">
          <p className="text-status-alarm text-sm">
            Failed to load gateway status. Retrying automatically…
          </p>
        </Card>
      )}

      {flushMutation.isError && (
        <Card className="p-4">
          <p className="text-status-alarm text-sm">
            Flush failed. The queued data could not be sent — please try again.
          </p>
        </Card>
      )}

      {/* Connection Status */}
      <Card className="p-6">
        <div className="flex items-center justify-between">
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-4">
                <div className={`p-4 rounded-xl ${!known ? 'bg-opsgrid-bg' : isConnected ? 'bg-status-running/20' : 'bg-status-offline/20'}`}>
                  <Cloud className={`w-10 h-10 ${!known ? 'text-opsgrid-text-secondary' : isConnected ? 'text-status-running' : 'text-status-offline'}`} />
                </div>
                <div>
                  <h2 className="text-2xl font-bold">
                    {!known ? 'Status unknown' : isConnected ? 'Connected' : 'Disconnected'}
                  </h2>
                  <p className="text-opsgrid-text-secondary">
                    {status?.endpoint
                      ? `Endpoint: ${status.endpoint}`
                      : known
                        ? 'Endpoint unknown'
                        : 'The gateway did not report — this is not a report of no gateway.'}
                  </p>
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent>Cloud gateway connection status</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant={!known ? 'default' : isConnected ? 'success' : 'error'} size="md">
                {!known ? 'Unknown' : isConnected ? 'Online' : 'Offline'}
              </Badge>
            </TooltipTrigger>
            <TooltipContent>
              {!known
                ? 'The gateway status could not be read; its connection state is unknown'
                : isConnected
                  ? 'Gateway is connected to cloud'
                  : 'Gateway is disconnected from cloud'}
            </TooltipContent>
          </Tooltip>
        </div>
      </Card>

      {/* Quick Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Clock className="w-5 h-5 text-opsgrid-primary" />
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Queue Depth</p>
                  {/* `?? 0` said the edge had nothing waiting to upload. An operator
                      reads an empty queue as "no data is stranded" and stops looking. */}
                  <p className="font-medium">
                    {known ? `${status.queueSize} items` : 'Unknown'}
                  </p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Number of items awaiting upload to the cloud</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Shield className="w-5 h-5 text-opsgrid-primary" />
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">mTLS</p>
                  <p className="font-medium">
                    {known ? (status.mtlsEnabled ? 'Enabled' : 'Disabled') : 'Unknown'}
                  </p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Whether mutual TLS is enabled on the gateway connection</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Server className="w-5 h-5 text-opsgrid-primary" />
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Endpoint</p>
                  <p className="font-medium truncate">{status?.endpoint || '—'}</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Cloud endpoint host the gateway targets</TooltipContent>
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
                disabled={!known || !isConnected || flushMutation.isPending}
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
        <div className="p-4 bg-opsgrid-bg rounded-lg">
          <div className="flex items-center gap-3 mb-2">
            <Shield className={`w-5 h-5 ${!known ? 'text-opsgrid-text-secondary' : status.mtlsEnabled ? 'text-status-running' : 'text-status-offline'}`} />
            <p className="font-medium">
              {!known ? 'mTLS state unknown' : status.mtlsEnabled ? 'mTLS Enabled' : 'mTLS Disabled'}
            </p>
          </div>
          {/* THE SHARPEST OF THE FOUR. This asserted that mutual TLS was not enabled on a
              connection nobody had managed to inspect — a security conclusion drawn from a
              failed request, printed under a red shield. */}
          <p className="text-sm text-opsgrid-text-secondary">
            {!known
              ? 'The gateway status could not be read, so its encryption state is unknown. This is not a finding that mTLS is disabled.'
              : status.mtlsEnabled
                ? 'Mutual TLS authentication secures bidirectional communication with the cloud.'
                : 'Mutual TLS is not enabled on this gateway connection.'}
          </p>
        </div>
      </Card>
    </div>
  );
};
