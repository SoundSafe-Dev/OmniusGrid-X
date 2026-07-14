import React from 'react';
import { AbsoluteFill } from 'remotion';
import Dashboard from '../../../src/pages/Dashboard';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { LiftFocus } from '../mobile/components/LiftFocus';
import { NavDrawer } from '../components/NavDrawer';

/** Chain scene (shop floor): full dashboard, the Active Alarms stat card
 *  lifted big, then the alarms panel spotlighted at full frame. */
export const DashboardScene: React.FC = () => (
  <AbsoluteFill>
    <AppFrame route="/">
      <PanZoom
        moves={[
          { at: 0, scale: 1.0, focusX: 960, focusY: 518 },
          { at: 62, scale: 1.0, focusX: 960, focusY: 518 },
          // Active Alarms stat card, lifted
          { at: 70, scale: 1.7, focusX: 1199, focusY: 150 },
          { at: 100, scale: 1.7, focusX: 1199, focusY: 152 },
          // the alarms panel spans the full page width — spotlight at full view
          { at: 108, scale: 1.0, focusX: 960, focusY: 518 },
          { at: 182, scale: 1.0, focusX: 960, focusY: 518 },
        ]}
      >
        <Dashboard />
        <LiftFocus x={966} y={4} w={466} h={84} inAt={66} outAt={104} radius={10} />
        <LiftFocus x={22} y={392} w={1876} h={304} inAt={112} outAt={148} radius={14} />
      </PanZoom>
      <NavDrawer activePath="/" targetPath="/oee" inAt={156} clickAt={174} />
    </AppFrame>
    <Caption
      text="The shop floor, live — every metric already feeding the correlation engine."
      accent="every metric"
      inAt={10}
      outAt={126}
    />
  </AbsoluteFill>
);
