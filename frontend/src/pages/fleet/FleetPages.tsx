import { FC, useState } from 'react';
import { Building2, MapPin, Users, ChevronRight, ChevronDown, Factory, Box, Activity } from 'lucide-react';
import { Card, Badge } from '../../components';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';

export const FleetOverview: FC = () => {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Building2 className="w-8 h-8 text-opsgrid-primary" />
                <div>
                  <p className="text-2xl font-bold">3</p>
                  <p className="text-sm text-opsgrid-text-secondary">Sites</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Total manufacturing sites in the fleet</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <MapPin className="w-8 h-8 text-opsgrid-primary" />
                <div>
                  <p className="text-2xl font-bold">7</p>
                  <p className="text-sm text-opsgrid-text-secondary">Workcells</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Total workcells across all sites</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <Users className="w-8 h-8 text-opsgrid-primary" />
                <div>
                  <p className="text-2xl font-bold">24</p>
                  <p className="text-sm text-opsgrid-text-secondary">Total Assets</p>
                </div>
              </div>
            </Card>
          </TooltipTrigger>
          <TooltipContent>Total assets across the entire fleet</TooltipContent>
        </Tooltip>
      </div>

      <Card title="Site Overview" subtitle="Manufacturing locations">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {['Main Factory', 'Assembly Plant', 'Distribution Center'].map((site) => (
            <Tooltip key={site}>
              <TooltipTrigger asChild>
                <div className="p-4 bg-opsgrid-bg rounded-lg">
                  <h3 className="font-semibold">{site}</h3>
                  <div className="mt-2 flex items-center gap-2">
                    <Badge variant="success" size="sm">Online</Badge>
                    <span className="text-sm text-opsgrid-text-secondary">8 assets</span>
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent>View assets and workcells at {site}</TooltipContent>
            </Tooltip>
          ))}
        </div>
      </Card>
    </div>
  );
};

export const OrganizationTree: FC = () => {
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set(['org']));

  // Mock organization data
  const orgData = {
    id: 'org',
    name: 'OmniusGrid Corporation',
    type: 'organization',
    children: [
      {
        id: 'site-1',
        name: 'Main Factory',
        type: 'site',
        status: 'online',
        children: [
          {
            id: 'wc-1',
            name: 'Workcell A',
            type: 'workcell',
            children: [
              { id: 'asset-1', name: 'Printer #1 (Bambu X1)', type: 'asset', status: 'online' },
              { id: 'asset-2', name: 'Printer #2 (Bambu X1)', type: 'asset', status: 'online' },
              { id: 'asset-3', name: 'Printer #3 (Bambu X1)', type: 'asset', status: 'warning' },
            ]
          },
          {
            id: 'wc-2',
            name: 'Workcell B',
            type: 'workcell',
            children: [
              { id: 'asset-4', name: 'Conveyor #1', type: 'asset', status: 'online' },
              { id: 'asset-5', name: 'Conveyor #2', type: 'asset', status: 'online' },
              { id: 'asset-6', name: 'CNC Machine #1', type: 'asset', status: 'online' },
              { id: 'asset-7', name: 'CNC Machine #2', type: 'asset', status: 'offline' },
              { id: 'asset-8', name: 'Hydraulic Press #1', type: 'asset', status: 'online' },
            ]
          }
        ]
      },
      {
        id: 'site-2',
        name: 'Assembly Plant',
        type: 'site',
        status: 'online',
        children: [
          {
            id: 'wc-3',
            name: 'Workcell C',
            type: 'workcell',
            children: [
              { id: 'asset-9', name: 'Assembly Line #1', type: 'asset', status: 'online' },
              { id: 'asset-10', name: 'Assembly Line #2', type: 'asset', status: 'online' },
              { id: 'asset-11', name: 'Robot Arm #1', type: 'asset', status: 'online' },
              { id: 'asset-12', name: 'Robot Arm #2', type: 'asset', status: 'warning' },
            ]
          },
          {
            id: 'wc-4',
            name: 'Workcell D',
            type: 'workcell',
            children: [
              { id: 'asset-13', name: 'Quality Station #1', type: 'asset', status: 'online' },
              { id: 'asset-14', name: 'Quality Station #2', type: 'asset', status: 'online' },
              { id: 'asset-15', name: 'Packaging Unit #1', type: 'asset', status: 'online' },
              { id: 'asset-16', name: 'Packaging Unit #2', type: 'asset', status: 'offline' },
            ]
          }
        ]
      },
      {
        id: 'site-3',
        name: 'Distribution Center',
        type: 'site',
        status: 'online',
        children: [
          {
            id: 'wc-5',
            name: 'Workcell E',
            type: 'workcell',
            children: [
              { id: 'asset-17', name: 'Loading Dock #1', type: 'asset', status: 'online' },
              { id: 'asset-18', name: 'Loading Dock #2', type: 'asset', status: 'online' },
              { id: 'asset-19', name: 'Forklift #1', type: 'asset', status: 'online' },
              { id: 'asset-20', name: 'Forklift #2', type: 'asset', status: 'online' },
            ]
          },
          {
            id: 'wc-6',
            name: 'Workcell F',
            type: 'workcell',
            children: [
              { id: 'asset-21', name: 'Storage System #1', type: 'asset', status: 'online' },
              { id: 'asset-22', name: 'Storage System #2', type: 'asset', status: 'online' },
              { id: 'asset-23', name: 'Sorting Machine #1', type: 'asset', status: 'online' },
              { id: 'asset-24', name: 'Sorting Machine #2', type: 'asset', status: 'warning' },
            ]
          }
        ]
      }
    ]
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

  return (
    <Card title="Organization Structure" subtitle="Hierarchical view of assets">
      <div className="p-4 bg-opsgrid-bg rounded-lg h-[calc(100vh-250px)] overflow-y-auto">
        {renderNode(orgData)}
      </div>
    </Card>
  );
};
