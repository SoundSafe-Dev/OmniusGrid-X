import React from 'react';
import { AbsoluteFill } from 'remotion';
import Dashboard from '../../../../src/pages/Dashboard';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { MobileNavDrawer } from '../MobileNavDrawer';
import { LiftFocus } from '../components/LiftFocus';
import { M_FULL } from '../theme';

/** Portrait dashboard: stat-card punch, then full-width alarms spotlight. */
export const MobileDashboardScene: React.FC = () => (
  <AbsoluteFill>
    <MobileAppFrame route="/">
      <MobilePanZoom
        moves={[
          { at: 0, ...M_FULL },
          { at: 55, ...M_FULL },
          // Active Alarms stat card, lifted big
          { at: 72, scale: 2.0, focusX: 1199, focusY: 46 },
          { at: 94, scale: 2.0, focusX: 1199, focusY: 50 },
          // first alarm row, lifted — subtle drift, title stays in frame
          { at: 104, scale: 1.15, focusX: 490, focusY: 502 },
          { at: 124, scale: 1.15, focusX: 510, focusY: 504 },
          { at: 132, ...M_FULL },
          { at: 148, ...M_FULL },
        ]}
      >
        <Dashboard />
        <LiftFocus x={966} y={4} w={466} h={84} inAt={66} outAt={96} radius={10} />
        <LiftFocus x={20} y={462} w={950} h={80} inAt={104} outAt={126} fadeEdge="right" radius={10} />
      </MobilePanZoom>
      <MobileNavDrawer activePath="/" targetPath="/oee" inAt={128} clickAt={146} />
    </MobileAppFrame>
    <MobileCaption
      text="The shop floor, live — every metric already feeding the correlation engine."
      accent="every metric"
      inAt={10}
      outAt={102}
    />
  </AbsoluteFill>
);
