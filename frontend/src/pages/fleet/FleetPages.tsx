import { FC, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Building2, MapPin, Users, ChevronRight, ChevronDown, Factory, Box, Activity } from 'lucide-react';
import { Card, Badge, SkeletonCard } from '../../components';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';
import { GeoTabIntegration } from '../../components/fleet/GeoTabIntegration';
import { workcellsApi, assetsApi, organizationsApi } from '../../api';
import { AgentOperationsPanel } from './AgentOperationsPanel';

export const FleetOverview: FC = () => {
  const { data: workcells, isLoading: workcellsLoading, isError: workcellsError } = useQuery({ queryKey: ['fleet-workcells'], queryFn: () => workcellsApi.list() });
  const { data: assetsPage, isLoading: assetsLoading, isError: assetsError } = useQuery({ queryKey: ['fleet-assets'], queryFn: () => assetsApi.list({ limit: 500 }) });
  const { data: orgs } = useQuery({ queryKey: ['fleet-orgs'], queryFn: () => organizationsApi.list() });
  const orgId = orgs?.[0]?.id;

  const assets = assetsPage?.items ?? [];
  const workcellList = workcells ?? [];
  const onlineCount = assets.filter((a) => a.currentPackmlState === 'Execute').length;
  const assetsByWorkcell = (id: string) => assets.filter((a) => a.workcellId === id).length;

  const tiles = [
    { icon: MapPin, value: workcellList.length, label: 'Workcells', tip: 'Total workcells in your organization' },
    { icon: Users, value: assetsPage?.total ?? assets.length, label: 'Total Assets', tip: 'Total assets across the fleet' },
    { icon: Activity, value: onlineCount, label: 'Executing', tip: 'Assets currently in the PackML Execute state' },
  ];

  if (workcellsLoading || assetsLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  if (workcellsError || assetsError) {
    return (
      <Card className="p-4">
        <p className="text-status-alarm text-sm">
          Failed to load fleet data. Please try again.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <AgentOperationsPanel />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {tiles.map(({ icon: Icon, value, label, tip }) => (
          <Tooltip key={label}>
            <TooltipTrigger asChild>
              <Card className="p-4">
                <div className="flex items-center gap-3">
                  <Icon className="w-8 h-8 text-opsgrid-primary" />
                  <div>
                    <p className="text-2xl font-bold">{value}</p>
                    <p className="text-sm text-opsgrid-text-secondary">{label}</p>
                  </div>
                </div>
              </Card>
            </TooltipTrigger>
            <TooltipContent>{tip}</TooltipContent>
          </Tooltip>
        ))}
      </div>

      <Card title="Workcells" subtitle="Production areas in your organization">
        {workcellList.length === 0 ? (
          <p className="text-sm text-opsgrid-text-secondary">No workcells configured.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {workcellList.map((wc) => (
              <Tooltip key={wc.id}>
                <TooltipTrigger asChild>
                  <div className="p-4 bg-opsgrid-bg rounded-lg">
                    <h3 className="font-semibold">{wc.name}</h3>
                    <div className="mt-2 flex items-center gap-2">
                      {wc.location && <Badge variant="default" size="sm">{wc.location}</Badge>}
                      <span className="text-sm text-opsgrid-text-secondary">{assetsByWorkcell(wc.id)} assets</span>
                    </div>
                  </div>
                </TooltipTrigger>
                <TooltipContent>{wc.description || `Assets in ${wc.name}`}</TooltipContent>
              </Tooltip>
            ))}
          </div>
        )}
      </Card>

      {/* Live vehicle tracking (FS-62): GeoTab telematics map — vehicles,
          geofences, and websocket position updates. Renders its own Card. */}
      {orgId && <GeoTabIntegration organizationId={orgId} height={480} />}
    </div>
  );
};

// PackML state -> tree node status color bucket.
const packmlStatus = (state?: string): string => {
  if (!state) return 'offline';
  if (state === 'Execute' || state === 'Idle') return 'online';
  if (['Aborted', 'Aborting', 'Stopped', 'Stopping'].includes(state)) return 'warning';
  return 'offline';
};

export const OrganizationTree: FC = () => {
  const { data: orgs, isLoading: orgsLoading, isError: orgsError } = useQuery({ queryKey: ['orgtree-orgs'], queryFn: () => organizationsApi.list() });
  const { data: workcells, isLoading: workcellsLoading, isError: workcellsError } = useQuery({ queryKey: ['orgtree-workcells'], queryFn: () => workcellsApi.list() });
  const { data: assetsPage, isLoading: assetsLoading, isError: assetsError } = useQuery({ queryKey: ['orgtree-assets'], queryFn: () => assetsApi.list({ limit: 500 }) });

  const org = orgs?.[0];
  // Constant root node id so the default-expanded set stays valid once the org
  // query resolves (a useState initializer never re-runs on later renders).
  const ROOT_ID = 'org-root';
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set([ROOT_ID]));

  // Real org -> workcell -> asset tree (the data model has no "site" tier).
  const assets = assetsPage?.items ?? [];
  const orgData = {
    id: ROOT_ID,
    name: org?.name ?? 'Organization',
    type: 'organization',
    children: (workcells ?? []).map((wc) => ({
      id: wc.id,
      name: wc.name,
      type: 'workcell',
      children: assets
        .filter((a) => a.workcellId === wc.id)
        .map((a) => ({
          id: a.id,
          name: a.name,
          type: 'asset',
          status: packmlStatus(a.currentPackmlState),
        })),
    })),
  };

  const toggleNode = (nodeId: string) => {
    const newExpanded = new Set(expandedNodes);
    if (newExpanded.has(nodeId)) {
      newExpanded.delete(nodeId);
    } else {
      newExpanded.add(nodeId);
    }
    setExpandedNodes(newExpanded);
  };

  const getNodeIcon = (type: string) => {
    switch (type) {
      case 'organization': return <Building2 className="w-4 h-4" />;
      case 'site': return <MapPin className="w-4 h-4" />;
      case 'workcell': return <Factory className="w-4 h-4" />;
      case 'asset': return <Box className="w-4 h-4" />;
      default: return <Activity className="w-4 h-4" />;
    }
  };

  const getStatusColor = (status?: string) => {
    switch (status) {
      case 'online': return 'text-green-500';
      case 'offline': return 'text-gray-400';
      case 'warning': return 'text-yellow-500';
      default: return 'text-gray-400';
    }
  };

  const renderNode = (node: any, level: number = 0) => {
    const isExpanded = expandedNodes.has(node.id);
    const hasChildren = node.children && node.children.length > 0;

    return (
      <div key={node.id} className="select-none">
        <div
          className={`flex items-center gap-2 py-2 px-3 rounded hover:bg-opsgrid-bg cursor-pointer transition-colors`}
          style={{ paddingLeft: `${level * 16 + 12}px` }}
          onClick={() => hasChildren && toggleNode(node.id)}
        >
          {hasChildren && (
            <span className="text-opsgrid-text-secondary">
              {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </span>
          )}
          {!hasChildren && <span className="w-4" />}
          <span className={node.status ? getStatusColor(node.status) : 'text-opsgrid-primary'}>
            {getNodeIcon(node.type)}
          </span>
          <span className="text-sm text-opsgrid-text-primary">{node.name}</span>
          {node.status && (
            <Badge variant={node.status === 'online' ? 'success' : node.status === 'warning' ? 'warning' : 'info'} size="sm">
              {node.status}
            </Badge>
          )}
          {hasChildren && (
            <span className="text-xs text-opsgrid-text-secondary ml-auto">
              {node.children.length}
            </span>
          )}
        </div>
        {isExpanded && hasChildren && (
          <div>
            {node.children.map((child: any) => renderNode(child, level + 1))}
          </div>
        )}
      </div>
    );
  };

  const isLoading = orgsLoading || workcellsLoading || assetsLoading;
  const isError = orgsError || workcellsError || assetsError;

  return (
    <Card title="Organization Structure" subtitle="Hierarchical view of assets">
      <div className="p-4 bg-opsgrid-bg rounded-lg h-[calc(100vh-250px)] overflow-y-auto">
        {isLoading ? (
          <SkeletonCard lines={6} />
        ) : isError ? (
          <p className="text-status-alarm text-sm">
            Failed to load organization structure. Please try again.
          </p>
        ) : (
          renderNode(orgData)
        )}
      </div>
    </Card>
  );
};
