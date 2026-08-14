import { FC, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Cpu, RotateCcw, Download, CheckCircle } from 'lucide-react';
import { Card, Badge, Button, Select, SkeletonCard, EngineStoppedBanner } from '../../components';
import { enginesApi } from '../../api';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';

export const MLOpsPipeline: FC = () => {
  const queryClient = useQueryClient();
  const [selectedVersion, setSelectedVersion] = useState('');

  const { data: status, isLoading, isError } = useQuery({
    queryKey: ['mlops-status'],
    queryFn: () => enginesApi.getMLOpsStatus(),
    refetchInterval: 30000,
  });

  const deployMutation = useMutation({
    mutationFn: (version: string) => enginesApi.deployModel(version),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['mlops-status'] }),
  });

  const rollbackMutation = useMutation({
    mutationFn: () => enginesApi.rollbackModel(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['mlops-status'] }),
  });

  const actionError = deployMutation.isError || rollbackMutation.isError;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={6} />
      </div>
    );
  }

  const availableVersions = status?.cachedModels || [];
  // A rollback target exists only when a cached model other than the current
  // one is available; the backend performs no rollback with a single version.
  const canRollback = availableVersions.some((v) => v !== status?.currentModel);

  return (
    <div className="space-y-6">
      <EngineStoppedBanner running={status?.running} note={status?.note} />
      {isError && (
        <Card className="p-4">
          <p className="text-status-alarm text-sm">
            Failed to load MLOps status. Retrying automatically…
          </p>
        </Card>
      )}

      {actionError && (
        <Card className="p-4">
          <p className="text-status-alarm text-sm">
            Action failed. The model operation did not complete — please try again.
          </p>
        </Card>
      )}

      {/* Current Model */}
      <Card title="Current Model" subtitle="Active deployment">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center justify-between p-4 bg-opsgrid-bg rounded-lg">
              <div className="flex items-center gap-4">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="p-3 bg-opsgrid-primary/20 rounded-lg">
                      <Cpu className="w-6 h-6 text-opsgrid-primary" />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>ML model icon</TooltipContent>
                </Tooltip>
                <div>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      {/* `status` is undefined on a failed fetch, so the `||` fallback
                          asserted "No model deployed" — which an MLOps operator reads as
                          "nothing is in production" and may act on by deploying. The
                          fallback now distinguishes a failed read from an empty one. */}
                      <p className="text-lg font-semibold">
                        {isError
                          ? 'Model status unavailable'
                          : status?.currentModel || 'No model deployed'}
                      </p>
                    </TooltipTrigger>
                    <TooltipContent>Currently deployed model version</TooltipContent>
                  </Tooltip>
                </div>
              </div>
              <Tooltip>
                <TooltipTrigger asChild>
                  {/* HARDCODED `success` / "Active", beside the very text that was
                      already corrected to say "Model status unavailable". A green tick
                      reading Active next to a failed read is the more confident of the
                      two statements, and it was not derived from anything at all — it
                      also said Active when `currentModel` was empty and the line beside
                      it said "No model deployed". Rule 24: the neighbour of a handled
                      error is where the unhandled claim survives. */}
                  <Badge
                    variant={isError ? 'default' : status?.currentModel ? 'success' : 'warning'}
                    size="md"
                  >
                    {!isError && status?.currentModel && (
                      <CheckCircle size={14} className="mr-1" />
                    )}
                    {isError ? 'Unknown' : status?.currentModel ? 'Active' : 'None'}
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>
                  {isError
                    ? 'The MLOps status could not be read; no deployment state is known'
                    : status?.currentModel
                      ? 'Model is currently active in production'
                      : 'No model is deployed'}
                </TooltipContent>
              </Tooltip>
            </div>
          </TooltipTrigger>
          <TooltipContent>Current ML model deployment information</TooltipContent>
        </Tooltip>
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
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="primary"
                disabled={!selectedVersion || deployMutation.isPending}
                loading={deployMutation.isPending}
                onClick={() => deployMutation.mutate(selectedVersion)}
              >
                <Download size={16} className="mr-1" />
                Deploy
              </Button>
            </TooltipTrigger>
            <TooltipContent>Deploy selected model version to production</TooltipContent>
          </Tooltip>
        </div>
      </Card>

      {/* Rollback */}
      <Card title="Rollback" subtitle="Revert to previous version">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center justify-between p-4 bg-opsgrid-bg rounded-lg">
              <div>
                <p className="font-medium">Quick Rollback</p>
                <p className="text-sm text-opsgrid-text-secondary">
                  Revert to the previous model version immediately
                </p>
              </div>
              <Button
                variant="danger"
                disabled={rollbackMutation.isPending || !canRollback}
                loading={rollbackMutation.isPending}
                onClick={() => rollbackMutation.mutate()}
              >
                <RotateCcw size={16} className="mr-1" />
                Rollback
              </Button>
            </div>
          </TooltipTrigger>
          <TooltipContent>Revert to the previous model version</TooltipContent>
        </Tooltip>
      </Card>

      {/* Registry Status */}
      <Card title="Registry Status" subtitle="Model registry connection">
        <div className="grid grid-cols-2 gap-4">
          <div className="p-3 bg-opsgrid-bg rounded-lg">
            <p className="text-sm text-opsgrid-text-secondary">Poll Interval</p>
            {/* `|| 300` printed a number the registry never reported — a fabricated
                configuration value, indistinguishable on screen from a real one. */}
            <p className="font-medium">
              {isError || !status ? 'Unknown' : `${status.pollIntervalSeconds} seconds`}
            </p>
          </div>
          <div className="p-3 bg-opsgrid-bg rounded-lg">
            <p className="text-sm text-opsgrid-text-secondary">Available Models</p>
            {/* `availableVersions` is `status?.cachedModels || []`, so a failed fetch
                counted 0 — an empty model registry, which is a very different problem
                from an unreachable one and points an operator at the wrong system. */}
            <p className="font-medium">
              {isError || !status ? 'Unknown' : availableVersions.length}
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
};
