import { FC } from 'react';
import { Building2, MapPin, Users } from 'lucide-react';
import { Card, Badge, SkeletonCard } from '../../components';

export const FleetOverview: FC = () => {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="p-4">
          <div className="flex items-center gap-3">
            <Building2 className="w-8 h-8 text-opsgrid-primary" />
            <div>
              <p className="text-2xl font-bold">3</p>
              <p className="text-sm text-opsgrid-text-secondary">Sites</p>
            </div>
          </div>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-3">
            <MapPin className="w-8 h-8 text-opsgrid-primary" />
            <div>
              <p className="text-2xl font-bold">7</p>
              <p className="text-sm text-opsgrid-text-secondary">Workcells</p>
            </div>
          </div>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-3">
            <Users className="w-8 h-8 text-opsgrid-primary" />
            <div>
              <p className="text-2xl font-bold">24</p>
              <p className="text-sm text-opsgrid-text-secondary">Total Assets</p>
            </div>
          </div>
        </Card>
      </div>

      <Card title="Site Overview" subtitle="Manufacturing locations">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {['Main Factory', 'Assembly Plant', 'Distribution Center'].map((site) => (
            <div key={site} className="p-4 bg-opsgrid-bg rounded-lg">
              <h3 className="font-semibold">{site}</h3>
              <div className="mt-2 flex items-center gap-2">
                <Badge variant="success" size="sm">Online</Badge>
                <span className="text-sm text-opsgrid-text-secondary">8 assets</span>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};

export const OrganizationTree: FC = () => {
  return (
    <Card title="Organization Structure" subtitle="Hierarchical view of assets">
      <div className="p-4 bg-opsgrid-bg rounded-lg">
        <p className="text-opsgrid-text-secondary">Organization tree visualization will be displayed here</p>
      </div>
    </Card>
  );
};
