import { FC, useEffect, useMemo, useState } from 'react';
import {
  FileJson,
  RefreshCw,
  RotateCw,
  ShieldCheck,
  Stethoscope,
  TerminalSquare,
} from 'lucide-react';

import { handleApiError } from '../../api';
import { Badge, Button, Card, Input, Select,
  useDialog,
} from '../../components/ui';
import { useAuth } from '../../hooks/useAuth';
import {
  useAgentRemoteOperation,
  useFleetInventory,
  useSubmitAgentRemoteOperation,
} from '../../hooks/useFleet';
import {
  AgentRemoteOperationAction,
  AgentRemoteOperationResult,
} from '../../types/fleet';
import { formatDateTime, formatTimeAgo } from '../../utils';

const TERMINAL_STATUSES = new Set([
  'completed',
  'failed',
  'cancelled',
  'timeout',
]);

const STATUS_VARIANT = {
  pending: 'neutral',
  executing: 'info',
  completed: 'success',
  failed: 'error',
  cancelled: 'neutral',
  timeout: 'warning',
} as const;

interface ActiveCommand {
  assetId: string;
  commandId: string;
}

export const AgentOperationsPanel: FC = () => {
  const { confirm } = useDialog();
  const { isOperator } = useAuth();
  const inventory = useFleetInventory();
  const submit = useSubmitAgentRemoteOperation();
  const eligibleAssets = useMemo(
    () =>
      (inventory.data?.assets || []).filter(
        (asset) => asset.is_active && asset.agent_id
      ),
    [inventory.data]
  );
  const [assetId, setAssetId] = useState('');
  const [logLimit, setLogLimit] = useState('100');
  const [logLevel, setLogLevel] = useState('');
  const [active, setActive] = useState<ActiveCommand>({
    assetId: '',
    commandId: '',
  });
  const [requestError, setRequestError] = useState<string | null>(null);
  const command = useAgentRemoteOperation(active.assetId, active.commandId);

  useEffect(() => {
    if (!assetId && eligibleAssets.length > 0) {
      setAssetId(eligibleAssets[0].id);
    }
  }, [assetId, eligibleAssets]);

  const selectedAsset = eligibleAssets.find((asset) => asset.id === assetId);
  const operationBusy =
    submit.isPending ||
    Boolean(command.data && !TERMINAL_STATUSES.has(command.data.status));

  const startOperation = async (action: AgentRemoteOperationAction) => {
    if (!assetId) return;
    // A collector restart interrupts data capture on a live machine, so it is confirmed —
    // through the styled dialog rather than `window.confirm`, which some embedded contexts
    // suppress entirely and would let the restart proceed unconfirmed (FS-766).
    if (
      action === 'collector_restart' &&
      !(await confirm({
        title: 'Restart this collector?',
        message: `Data capture for "${selectedAsset?.name || assetId}" pauses until it comes back.`,
        confirmLabel: 'Restart collector',
      }))
    ) {
      return;
    }

    setRequestError(null);
    const payload =
      action === 'agent_fetch_logs'
        ? {
            schema_version: 1 as const,
            limit: Math.max(1, Math.min(200, Number(logLimit) || 100)),
            levels: logLevel
              ? [logLevel as 'debug' | 'info' | 'warning' | 'error' | 'critical']
              : [],
          }
        : action === 'collector_restart'
          ? {
              schema_version: 1 as const,
              readiness_timeout_seconds: 10,
            }
          : { schema_version: 1 as const };

    submit.mutate(
      { assetId, action, payload },
      {
        onSuccess: (created) => {
          setActive({
            assetId: created.asset_id,
            commandId: created.command_id,
          });
        },
        onError: (error) => setRequestError(handleApiError(error).message),
      }
    );
  };

  if (!isOperator) {
    return (
      <Card
        title="Remote agent operations"
        subtitle="Bounded support actions over the existing command channel"
      >
        <div className="flex items-start gap-3 text-sm text-opsgrid-text-secondary">
          <ShieldCheck className="mt-0.5 h-5 w-5 text-opsgrid-primary" />
          <p>
            An operator or administrator role is required to request agent logs,
            diagnostics, collector restarts, or effective configuration.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card
      title="Remote agent operations"
      subtitle="Audited, rate-limited support actions; no SSH or remote shell"
      action={
        command.data ? (
          <Badge variant={STATUS_VARIANT[command.data.status]}>
            {command.data.status}
          </Badge>
        ) : undefined
      }
    >
      <div className="space-y-5">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <Select
            label="Collector / route asset"
            value={assetId}
            onChange={(event) => {
              setAssetId(event.target.value);
              setRequestError(null);
            }}
            disabled={inventory.isLoading || operationBusy}
            placeholder={
              inventory.isLoading ? 'Loading fleet…' : 'Select an asset'
            }
            options={eligibleAssets.map((asset) => ({
              value: asset.id,
              label: `${asset.name} · ${asset.agent_id}`,
            }))}
            helperText={
              selectedAsset
                ? `Agent ${selectedAsset.agent_id} · v${selectedAsset.agent_version || 'unknown'} · ${
                    selectedAsset.last_heartbeat
                      ? `seen ${formatTimeAgo(selectedAsset.last_heartbeat)}`
                      : 'never reported'
                  }`
                : undefined
            }
          />
          <Input
            label="Log entry limit"
            type="number"
            min={1}
            max={200}
            value={logLimit}
            onChange={(event) => setLogLimit(event.target.value)}
            disabled={operationBusy}
          />
          <Select
            label="Log level"
            value={logLevel}
            onChange={(event) => setLogLevel(event.target.value)}
            disabled={operationBusy}
            options={[
              { value: '', label: 'All levels' },
              { value: 'debug', label: 'Debug' },
              { value: 'info', label: 'Info' },
              { value: 'warning', label: 'Warning' },
              { value: 'error', label: 'Error' },
              { value: 'critical', label: 'Critical' },
            ]}
          />
        </div>

        {inventory.isError && (
          <p role="alert" className="text-sm text-status-alarm">
            Fleet inventory could not be loaded.
          </p>
        )}
        {!inventory.isLoading && eligibleAssets.length === 0 && (
          <p className="text-sm text-opsgrid-text-secondary">
            No active assets currently report an edge-agent identity.
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            onClick={() => startOperation('agent_fetch_logs')}
            disabled={!assetId || operationBusy}
          >
            <TerminalSquare className="mr-2 h-4 w-4" />
            Fetch logs
          </Button>
          <Button
            variant="secondary"
            onClick={() => startOperation('agent_diagnostics')}
            disabled={!assetId || operationBusy}
          >
            <Stethoscope className="mr-2 h-4 w-4" />
            Run diagnostics
          </Button>
          <Button
            variant="secondary"
            onClick={() => startOperation('agent_effective_config')}
            disabled={!assetId || operationBusy}
          >
            <FileJson className="mr-2 h-4 w-4" />
            Effective config
          </Button>
          <Button
            variant="danger"
            onClick={() => startOperation('collector_restart')}
            disabled={!assetId || operationBusy}
          >
            <RotateCw className="mr-2 h-4 w-4" />
            Restart collector
          </Button>
        </div>

        {(requestError || command.isError || command.data?.error) && (
          <div
            role="alert"
            className="rounded-lg border border-status-alarm/40 bg-status-alarm/10 p-3 text-sm text-status-alarm"
          >
            {requestError ||
              (command.isError
                ? handleApiError(command.error).message
                : command.data?.error)}
          </div>
        )}

        {active.commandId && !command.data && !command.isError && (
          <div className="flex items-center gap-2 text-sm text-opsgrid-text-secondary">
            <RefreshCw className="h-4 w-4 animate-spin" />
            Loading durable command state…
          </div>
        )}

        {command.data && (
          <div className="space-y-3 border-t border-opsgrid-border pt-4">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-opsgrid-text-secondary">
              <span className="font-mono">
                Command {command.data.command_id}
              </span>
              <span>Action {command.data.action}</span>
              {command.data.issued_at && (
                <span title={formatDateTime(command.data.issued_at)}>
                  Requested {formatTimeAgo(command.data.issued_at)}
                </span>
              )}
            </div>
            {!TERMINAL_STATUSES.has(command.data.status) ? (
              <div className="flex items-center gap-2 text-sm text-opsgrid-text-secondary">
                <RefreshCw className="h-4 w-4 animate-spin" />
                Waiting for the edge acknowledgement…
              </div>
            ) : command.data.result ? (
              <OperationResult result={command.data.result} />
            ) : (
              <p className="text-sm text-opsgrid-text-secondary">
                No result payload was returned.
              </p>
            )}
          </div>
        )}
      </div>
    </Card>
  );
};

const OperationResult: FC<{ result: AgentRemoteOperationResult }> = ({
  result,
}) => {
  if ('error_code' in result) {
    return (
      <div className="rounded-lg bg-opsgrid-bg p-3 text-sm">
        <div className="font-medium text-status-alarm">{result.message}</div>
        <div className="mt-1 font-mono text-xs text-opsgrid-text-secondary">
          {result.error_code}
        </div>
      </div>
    );
  }

  if ('entries' in result) {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2 text-xs text-opsgrid-text-secondary">
          <span>
            {result.returned_count} of {result.available_count} matching entries
          </span>
          <span>· {result.redacted_fields} redacted fields</span>
          {result.truncated && <Badge variant="warning">truncated</Badge>}
        </div>
        <div className="max-h-96 space-y-2 overflow-auto rounded-lg bg-opsgrid-bg p-3">
          {result.entries.length === 0 ? (
            <p className="text-sm text-opsgrid-text-secondary">
              No matching log entries are in the agent ring buffer.
            </p>
          ) : (
            result.entries.map((entry, index) => (
              <div
                key={`${entry.timestamp}-${index}`}
                className="border-b border-opsgrid-border pb-2 font-mono text-xs last:border-0 last:pb-0"
              >
                <div className="flex flex-wrap gap-2">
                  <span className="text-opsgrid-text-secondary">
                    {formatDateTime(entry.timestamp)}
                  </span>
                  <span className="uppercase text-opsgrid-primary">
                    {entry.level}
                  </span>
                  <span className="text-opsgrid-text">{entry.event}</span>
                </div>
                {Object.keys(entry.fields).length > 0 && (
                  <pre className="mt-1 whitespace-pre-wrap break-all text-opsgrid-text-secondary">
                    {JSON.stringify(entry.fields, null, 2)}
                  </pre>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    );
  }

  if ('effective_config' in result) {
    return (
      <JsonResult
        title={`Effective config · ${result.redacted_fields} redacted · ${result.omitted_collectors} omitted`}
        value={result.effective_config}
        truncated={result.truncated}
      />
    );
  }

  if ('before' in result && 'after' in result) {
    return (
      <JsonResult
        title={`Collector ready in ${result.duration_ms} ms`}
        value={{ before: result.before, after: result.after }}
        truncated={false}
      />
    );
  }

  return (
    <JsonResult
      title={
        'overall_status' in result
          ? `Diagnostics: ${result.overall_status}`
          : 'Operation result'
      }
      value={result}
      truncated={'truncated' in result && Boolean(result.truncated)}
    />
  );
};

const JsonResult: FC<{
  title: string;
  value: unknown;
  truncated: boolean;
}> = ({ title, value, truncated }) => (
  <div className="space-y-2">
    <div className="flex items-center gap-2 text-sm font-medium text-opsgrid-text">
      {title}
      {truncated && <Badge variant="warning">truncated</Badge>}
    </div>
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-opsgrid-bg p-3 font-mono text-xs text-opsgrid-text-secondary">
      {JSON.stringify(value, null, 2)}
    </pre>
  </div>
);

export default AgentOperationsPanel;
