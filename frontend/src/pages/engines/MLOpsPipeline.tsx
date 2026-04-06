import { FC, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from 'react-query';
import { Cpu, History, RotateCcw, Download, CheckCircle } from 'lucide-react';
import { Card, Badge, Button, Select, SkeletonCard } from '../../components';
import { enginesApi } from '../../api';
import { formatDateTime } from '../../utils';

export const MLOpsPipeline: FC = () => {
  const queryClient = useQueryClient();
  const [selectedVersion, setSelectedVersion] = useState('');

  const { data: status, isLoading } = useQuery(
    'mlops-status',
    () => enginesApi.getMLOpsStatus(),
    { refetchInterval: 30000 }
  );

  const deployMutation = useMutation(
    (version: string) => enginesApi.deployModel(version),
    {
      onSuccess: () => queryClient.invalidateQueries('mlops-status'),
    }
  );

  const rollbackMutation = useMutation(
    () => enginesApi.rollbackModel(),
    {
      onSuccess: () => queryClient.invalidateQueries('mlops-status'),
    }
  );

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={6} />
      </div>
    );
  }

  const availableVersions = status?.cachedModels || [];
  const deploymentHistory = status?.deploymentHistory || [];

  return (
    <div className="space-y-6">
      {/* Current Model */}
      <Card title="Current Model" subtitle="Active deployment">
        <div className="flex items-center justify-between p-4 bg-opsgrid-bg rounded-lg">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-opsgrid-primary/20 rounded-lg">
              <Cpu className="w-6 h-6 text-opsgrid-primary" />
            </div>
            <div>
              <p className="text-lg font-semibold">{status?.currentModel || 'No model deployed'}</p>
              {status?.lastDeploymentAt && (
                <p className="text-sm text-opsgrid-text-secondary">
                  Deployed {formatDateTime(status.lastDeploymentAt)}
                </p>
              )}
            </div>
          </div>
          <Badge variant="success" size="md">
            <CheckCircle size={14} className="mr-1" />
            Active
          </Badge>
        </div>
      </Card>

      {/* Deploy New Model */}
      <Card title="Deploy Model" subtitle="Select a version from the registry">
        <div className="flex items-end gap-4">
          <div className="flex-1">
            <Select
              label="Model Version"
              placeholder="Select version to deploy"
              value={selectedVersion}
              onChange={(e) => setSelectedVersion(e.target.value)}
              options={availableVersions.map((v) => ({ value: v, label: v }))}
            />
          </div>
          <Button
            variant="primary"
            disabled={!selectedVersion || deployMutation.isLoading}
            loading={deployMutation.isLoading}
            onClick={() => deployMutation.mutate(selectedVersion)}
          >
            <Download size={16} className="mr-1" />
            Deploy
          </Button>
        </div>
      </Card>

      {/* Rollback */}
      <Card title="Rollback" subtitle="Revert to previous version">
        <div className="flex items-center justify-between p-4 bg-opsgrid-bg rounded-lg">
          <div>
            <p className="font-medium">Quick Rollback</p>
            <p className="text-sm text-opsgrid-text-secondary">
              Revert to the previous model version immediately
            </p>
          </div>
          <Button
            variant="danger"
            disabled={rollbackMutation.isLoading || deploymentHistory.length < 2}
            loading={rollbackMutation.isLoading}
            onClick={() => rollbackMutation.mutate()}
          >
            <RotateCcw size={16} className="mr-1" />
            Rollback
          </Button>
        </div>
      </Card>

      {/* Deployment History */}
      <Card title="Deployment History" subtitle="Recent model updates">
        <div className="space-y-2">
          {deploymentHistory.length === 0 ? (
            <p className="text-opsgrid-text-secondary text-center py-8">
              No deployment history available.
            </p>
          ) : (
            deploymentHistory.map((deployment, index) => (
              <div
                key={`${deployment.version}-${index}`}
                className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg"
              >
                <div className="flex items-center gap-3">
                  <History className="w-4 h-4 text-opsgrid-text-secondary" />
                  <div>
                    <p className="font-medium">{deployment.version}</p>
                    <p className="text-sm text-opsgrid-text-secondary">
                      {formatDateTime(deployment.deployedAt)}
                    </p>
                  </div>
                </div>
                {deployment.rolledBackAt ? (
                  <Badge variant="neutral" size="sm">Rolled back</Badge>
                ) : index === 0 ? (
                  <Badge variant="success" size="sm">Current</Badge>
                ) : null}
              </div>
            ))
          )}
        </div>
      </Card>

      {/* Registry Status */}
      <Card title="Registry Status" subtitle="Model registry connection">
        <div className="grid grid-cols-2 gap-4">
          <div className="p-3 bg-opsgrid-bg rounded-lg">
            <p className="text-sm text-opsgrid-text-secondary">Poll Interval</p>
            <p className="font-medium">{status?.pollIntervalSeconds || 300} seconds</p>
          </div>
          <div className="p-3 bg-opsgrid-bg rounded-lg">
            <p className="text-sm text-opsgrid-text-secondary">Available Models</p>
            <p className="font-medium">{availableVersions.length}</p>
          </div>
          <div className="p-3 bg-opsgrid-bg rounded-lg">
            <p className="text-sm text-opsgrid-text-secondary">Last Poll</p>
            <p className="font-medium">
              {status?.lastPollAt ? formatDateTime(status.lastPollAt) : 'Never'}
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
};
