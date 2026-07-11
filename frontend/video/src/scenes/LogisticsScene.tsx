import React from 'react';
import { TransportationManagement } from '../../../src/pages/logistics/TransportationManagement';
import { FramedScene } from '../components/FramedScene';
import { Highlight } from '../components/Interactions';
import { NavDrawer } from '../components/NavDrawer';

/**
 * Transportation (TMS) as a framed feature page: full view, live-fleet
 * stats, the live tracker map (real OSM tiles — the settle gate waits for
 * them), then the shipments table, pulling back before the sidebar
 * navigation to Yard (YMS).
 */
export const LogisticsScene: React.FC = () => (
  <FramedScene
    overline="Logistics · TMS"
    title="Transportation Management"
    bullets={[
      'Live fleet map, drivers and shipment status',
      'ETAs with delay risk on every lane',
      'CT-PAT compliance, geofencing & vehicle health',
    ]}
    route="/logistics/transportation"
    page={<TransportationManagement />}
    moves={[
      { at: 0, scale: 1.0, focusX: 960, focusY: 500 },
      { at: 55, scale: 1.0, focusX: 960, focusY: 500 },
      { at: 70, scale: 1.15, focusX: 900, focusY: 250 },
      { at: 92, scale: 1.15, focusX: 900, focusY: 250 },
      { at: 104, scale: 1.2, focusX: 960, focusY: 420 },
      { at: 126, scale: 1.2, focusX: 960, focusY: 435 },
      { at: 138, scale: 1.2, focusX: 940, focusY: 1040 },
      { at: 154, scale: 1.2, focusX: 940, focusY: 1060 },
      { at: 168, scale: 1.0, focusX: 960, focusY: 500 },
      { at: 182, scale: 1.0, focusX: 960, focusY: 500 },
    ]}
    overlays={
      <>
        {/* the live tracker map */}
        <Highlight x={155} y={212} w={1580} h={410} inAt={106} outAt={128} radius={14} />
        {/* first In Transit shipment row (table sits below the map) */}
        <Highlight x={215} y={1016} w={1440} h={88} inAt={140} outAt={156} />
      </>
    }
    stageOverlay={
      <NavDrawer
        activePath="/logistics/transportation"
        targetPath="/logistics/yard"
        inAt={172}
        clickAt={188}
      />
    }
  />
);
