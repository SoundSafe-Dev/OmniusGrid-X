import React from 'react';
import { TransportationManagement } from '../../../../src/pages/logistics/TransportationManagement';
import { MobileFramedScene } from '../MobileFramedScene';
import { LiftFocus } from '../components/LiftFocus';
import { NavDrawer } from '../../components/NavDrawer';

/**
 * Portrait TMS: stacked framed layout; the MiniStage internals (camera,
 * rings, in-frame NavDrawer) are identical to the desktop edition.
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
      { at: 55, scale: 0.554, focusX: 960, focusY: 750 },
      { at: 70, scale: 0.95, focusX: 560, focusY: 260 },
      { at: 92, scale: 0.95, focusX: 1360, focusY: 264 },
      { at: 104, scale: 0.648, focusX: 945, focusY: 417 },
      { at: 126, scale: 0.648, focusX: 945, focusY: 420 },
      { at: 138, scale: 0.83, focusX: 835, focusY: 1150 },
      { at: 154, scale: 0.83, focusX: 850, focusY: 1152 },
      { at: 168, scale: 0.554, focusX: 960, focusY: 750 },
      { at: 182, scale: 0.554, focusX: 960, focusY: 750 },
    ]}
    overlays={
      <>
        <LiftFocus x={14} y={86} w={1894} h={94} inAt={70} outAt={94} radius={10} />
        <LiftFocus x={155} y={212} w={1580} h={410} inAt={106} outAt={128} />
        <LiftFocus x={215} y={1106} w={1240} h={88} inAt={138} outAt={158} fadeEdge="right" radius={10} />
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
