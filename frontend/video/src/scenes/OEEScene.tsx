import React from 'react';
import { AbsoluteFill } from 'remotion';
import OEE from '../../../src/pages/OEE';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { LiftFocus } from '../mobile/components/LiftFocus';
import { NavDrawer } from '../components/NavDrawer';

/** Chain scene (insight): full OEE view, the Overall OEE card lifted, then
 *  the degraded CNC-spindle row panned from asset name to its 61% OEE. */
export const OEEScene: React.FC = () => (
  <AbsoluteFill>
    <AppFrame route="/oee">
      <PanZoom
        moves={[
          { at: 0, scale: 1.0, focusX: 960, focusY: 500 },
          { at: 56, scale: 1.0, focusX: 960, focusY: 500 },
          // Overall OEE stat card (true card 1294-1889 x 54-191)
          { at: 64, scale: 1.7, focusX: 1591, focusY: 122 },
          { at: 100, scale: 1.7, focusX: 1591, focusY: 124 },
          // degraded spindle row: lift + pan from asset name to the OEE value
          { at: 112, scale: 1.3, focusX: 430, focusY: 911 },
          { at: 146, scale: 1.3, focusX: 1240, focusY: 915 },
          { at: 158, scale: 1.0, focusX: 960, focusY: 500 },
          { at: 176, scale: 1.0, focusX: 960, focusY: 500 },
        ]}
      >
        <OEE />
        <LiftFocus x={1289} y={48} w={605} h={148} inAt={62} outAt={104} radius={12} />
        <LiftFocus x={14} y={860} w={1620} h={102} inAt={110} outAt={152} radius={10} />
      </PanZoom>
      <NavDrawer
        activePath="/oee"
        targetPath="/logistics/transportation"
        inAt={166}
        clickAt={184}
      />
    </AppFrame>
    <Caption
      text="Patterns you didn't know existed — surfaced by the correlation engine in seconds."
      accent="Patterns you didn't know existed"
      inAt={10}
      outAt={106}
    />
  </AbsoluteFill>
);
