import React from 'react';
import { TransportationManagement } from '../../../src/pages/logistics/TransportationManagement';
import { FramedScene } from '../components/FramedScene';
import { Cursor } from '../components/Interactions';
import { LiftFocus } from '../mobile/components/LiftFocus';
import { TabHover } from '../mobile/components/TabHover';
import { NavDrawer } from '../components/NavDrawer';

/**
 * Transportation (TMS) as a framed feature page: full view → live-fleet
 * stats (lifted, panned) → the live tracker map (real OSM tiles) → the tab
 * rail showcased with a cursor glide (Fleet & Drivers · Compliance ·
 * Geofencing · Health & Security · Performance) → the first In-Transit
 * shipment row. Tab-bar and row rects measured from card border lines.
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
      { at: 50, scale: 1.0, focusX: 960, focusY: 500 },
      // fleet stats, lifted + panned
      { at: 56, scale: 1.3, focusX: 500, focusY: 200 },
      { at: 84, scale: 1.3, focusX: 1400, focusY: 205 },
      // the live map
      { at: 94, scale: 1.16, focusX: 900, focusY: 418 },
      { at: 124, scale: 1.16, focusX: 940, focusY: 425 },
      // the tab rail — breadth of the module
      { at: 132, scale: 1.5, focusX: 530, focusY: 930 },
      { at: 170, scale: 1.5, focusX: 530, focusY: 932 },
      // first In-Transit shipment row
      { at: 178, scale: 1.5, focusX: 620, focusY: 1150 },
      { at: 202, scale: 1.5, focusX: 1100, focusY: 1152 },
      { at: 212, scale: 1.0, focusX: 960, focusY: 500 },
      { at: 226, scale: 1.0, focusX: 960, focusY: 500 },
    ]}
    overlays={
      <>
        {/* live-fleet stats row */}
        <LiftFocus x={14} y={86} w={1894} h={94} inAt={56} outAt={86} radius={10} />
        {/* the live tracker map */}
        <LiftFocus x={155} y={212} w={1580} h={410} inAt={96} outAt={126} />
        {/* tab rail: Shipments … Performance, hovered tabs react for real */}
        <LiftFocus x={14} y={908} w={1050} h={48} inAt={134} outAt={172} radius={10} />
        <TabHover
          steps={[
            { at: 138, index: 2 },
            { at: 148, index: 4 },
            { at: 158, index: 6 },
            { at: 168, index: 8 },
          ]}
          until={172}
        />
        <Cursor
          path={[
            { at: 138, x: 202, y: 926 },
            { at: 148, x: 440, y: 926 },
            { at: 158, x: 706, y: 926 },
            { at: 168, x: 991, y: 926 },
          ]}
          inAt={136}
          outAt={172}
        />
        {/* first In Transit shipment row */}
        <LiftFocus x={30} y={1106} w={1425} h={88} inAt={178} outAt={206} fadeEdge="right" radius={10} />
      </>
    }
    stageOverlay={
      <NavDrawer
        activePath="/logistics/transportation"
        targetPath="/logistics/yard"
        inAt={218}
        clickAt={236}
      />
    }
  />
);
