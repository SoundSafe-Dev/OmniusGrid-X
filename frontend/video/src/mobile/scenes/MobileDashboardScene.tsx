import React from 'react';
import { AbsoluteFill } from 'remotion';
import Dashboard from '../../../../src/pages/Dashboard';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { MobileNavDrawer } from '../MobileNavDrawer';
import { LiftFocus } from '../components/LiftFocus';
import { M_FULL } from '../theme';

/** Portrait dashboard: stat-card lift, then the alarm row with a drift. */
export const MobileDashboardScene: React.FC = () => (
  <AbsoluteFill>
    <MobileAppFrame route="/">
      <MobilePanZoom
        moves={[
          { at: 0, ...M_FULL },
          { at: 62, ...M_FULL },
          // Active Alarms stat card, lifted big
          { at: 70, scale: 2.0, focusX: 1199, focusY: 46 },
          { at: 100, scale: 2.0, focusX: 1199, focusY: 50 },
          // first alarm row, lifted — subtle drift, title stays in frame
          { at: 110, scale: 1.15, focusX: 490, focusY: 502 },
          { at: 146, scale: 1.15, focusX: 510, focusY: 504 },
          { at: 156, ...M_FULL },
          { at: 182, ...M_FULL },
        ]}
      >
        <Dashboard />
        <LiftFocus x={966} y={4} w={466} h={84} inAt={66} outAt={104} radius={10} />
        <LiftFocus x={20} y={462} w={950} h={80} inAt={110} outAt={148} fadeEdge="right" radius={10} />
      </MobilePanZoom>
      <MobileNavDrawer activePath="/" targetPath="/oee" inAt={156} clickAt={174} />
    </MobileAppFrame>
    <MobileCaption
      text="The shop floor, live — every metric already feeding the correlation engine."
      accent="every metric"
      inAt={10}
      outAt={126}
    />
  </AbsoluteFill>
);
