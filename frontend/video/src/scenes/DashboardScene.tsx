import React from 'react';
import { AbsoluteFill } from 'remotion';
import Dashboard from '../../../src/pages/Dashboard';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { Highlight } from '../components/Interactions';
import { NavDrawer } from '../components/NavDrawer';

/** Chain scene (shop floor): full dashboard first, then feature punches. */
export const DashboardScene: React.FC = () => (
  <AbsoluteFill>
    <AppFrame route="/">
      <PanZoom
        moves={[
          { at: 0, scale: 1.0, focusX: 960, focusY: 518 },
          { at: 55, scale: 1.0, focusX: 960, focusY: 518 },
          { at: 72, scale: 1.35, focusX: 1150, focusY: 220 },
          { at: 94, scale: 1.35, focusX: 1150, focusY: 220 },
          // pull back to full frame and spotlight the whole alarms panel —
          // it spans the full page width, so any zoom would cut the ring
          { at: 106, scale: 1.0, focusX: 960, focusY: 518 },
          { at: 148, scale: 1.0, focusX: 960, focusY: 518 },
        ]}
      >
        <Dashboard />
        {/* Active Alarms stat card, then the live alarms panel */}
        <Highlight x={966} y={4} w={466} h={84} inAt={74} outAt={94} />
        <Highlight x={22} y={392} w={1876} h={304} inAt={108} outAt={126} radius={14} />
      </PanZoom>
      <NavDrawer activePath="/" targetPath="/oee" inAt={128} clickAt={146} />
    </AppFrame>
    <Caption
      text="The shop floor, live — every metric already feeding the correlation engine."
      accent="every metric"
      inAt={10}
      outAt={102}
    />
  </AbsoluteFill>
);
