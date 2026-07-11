import React from 'react';
import { AbsoluteFill } from 'remotion';
import OEE from '../../../../src/pages/OEE';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { MobileNavDrawer } from '../MobileNavDrawer';
import { LiftFocus } from '../components/LiftFocus';
import { M_FULL } from '../theme';

/** Portrait OEE: stat cards, then the degraded CNC-spindle row. */
export const MobileOEEScene: React.FC = () => (
  <AbsoluteFill>
    <MobileAppFrame route="/oee">
      <MobilePanZoom
        moves={[
          { at: 0, ...M_FULL },
          { at: 45, ...M_FULL },
          // Overall OEE stat card, lifted
          { at: 62, scale: 1.6, focusX: 1612, focusY: 135 },
          { at: 85, scale: 1.6, focusX: 1612, focusY: 137 },
          // degraded spindle row: lift + pan from asset name to the OEE value
          { at: 100, scale: 1.3, focusX: 430, focusY: 911 },
          { at: 122, scale: 1.3, focusX: 1240, focusY: 915 },
          { at: 134, ...M_FULL },
          { at: 152, ...M_FULL },
        ]}
      >
        <OEE />
        <LiftFocus x={1320} y={58} w={585} h={125} inAt={60} outAt={88} radius={10} />
        <LiftFocus x={14} y={860} w={1620} h={102} inAt={100} outAt={128} radius={10} />
      </MobilePanZoom>
      <MobileNavDrawer
        activePath="/oee"
        targetPath="/logistics/transportation"
        inAt={140}
        clickAt={158}
      />
    </MobileAppFrame>
    <MobileCaption
      text="Patterns you didn't know existed — surfaced by the correlation engine in seconds."
      accent="Patterns you didn't know existed"
      inAt={10}
      outAt={88}
    />
  </AbsoluteFill>
);
