import React from 'react';
import { TransportationManagement } from '../../../../src/pages/logistics/TransportationManagement';
import { MobileFramedScene } from '../MobileFramedScene';
import { Cursor } from '../../components/Interactions';
import { LiftFocus } from '../components/LiftFocus';
import { TabHover } from '../components/TabHover';
import { NavDrawer } from '../../components/NavDrawer';

/**
 * Portrait TMS: full tall page → fleet stats (lifted, panned) → live map →
 * the tab rail showcased with a cursor glide + real hover reactions → the
 * first In-Transit shipment row. Same beats and page rects as desktop.
 */
export const MobileLogisticsScene: React.FC = () => (
  <MobileFramedScene
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
      // portrait-window cameras (viewport 1064x906, fit-width 0.554)
      { at: 0, scale: 0.554, focusX: 960, focusY: 750 },
      { at: 50, scale: 0.554, focusX: 960, focusY: 750 },
      // fleet stats
      { at: 56, scale: 0.95, focusX: 560, focusY: 260 },
      { at: 84, scale: 0.95, focusX: 1360, focusY: 264 },
      // the live map
      { at: 94, scale: 0.648, focusX: 945, focusY: 417 },
      { at: 124, scale: 0.648, focusX: 945, focusY: 420 },
      // the tab rail
      { at: 132, scale: 0.97, focusX: 545, focusY: 930 },
      { at: 170, scale: 0.97, focusX: 545, focusY: 932 },
      // first In-Transit shipment row
      { at: 178, scale: 0.83, focusX: 660, focusY: 1150 },
      { at: 202, scale: 0.83, focusX: 880, focusY: 1152 },
      { at: 212, scale: 0.554, focusX: 960, focusY: 750 },
      { at: 226, scale: 0.554, focusX: 960, focusY: 750 },
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
