import React from 'react';
import { AbsoluteFill } from 'remotion';
import OEE from '../../../../src/pages/OEE';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { MobileNavDrawer } from '../MobileNavDrawer';
import { LiftFocus } from '../components/LiftFocus';
import { M_FULL } from '../theme';

/** Portrait OEE: Overall OEE card, then the degraded CNC-spindle row. */
export const MobileOEEScene: React.FC = () => (
  <AbsoluteFill>
    <MobileAppFrame route="/oee">
      <MobilePanZoom
        moves={[
          { at: 0, ...M_FULL },
          { at: 56, ...M_FULL },
          // Overall OEE stat card (true card 1294-1889 x 54-191)
          { at: 64, scale: 1.63, focusX: 1591, focusY: 122 },
          { at: 100, scale: 1.63, focusX: 1591, focusY: 124 },
          // degraded spindle row: lift + pan from asset name to the OEE value
          { at: 112, scale: 1.3, focusX: 430, focusY: 911 },
          { at: 146, scale: 1.3, focusX: 1240, focusY: 915 },
          { at: 158, ...M_FULL },
          { at: 176, ...M_FULL },
        ]}
      >
        <OEE />
        <LiftFocus x={1289} y={48} w={605} h={148} inAt={62} outAt={104} radius={12} />
        <LiftFocus x={14} y={860} w={1620} h={102} inAt={110} outAt={152} radius={10} />
      </MobilePanZoom>
      <MobileNavDrawer
        activePath="/oee"
        targetPath="/logistics/transportation"
        inAt={166}
        clickAt={184}
      />
    </MobileAppFrame>
    <MobileCaption
      text="Patterns you didn't know existed — surfaced by the correlation engine in seconds."
      accent="Patterns you didn't know existed"
      inAt={10}
      outAt={106}
    />
  </AbsoluteFill>
);
