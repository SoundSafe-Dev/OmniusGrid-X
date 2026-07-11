import React from 'react';
import { AbsoluteFill } from 'remotion';
import OEE from '../../../src/pages/OEE';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { Highlight } from '../components/Interactions';
import { NavDrawer } from '../components/NavDrawer';

/** Chain scene (insight): full OEE view, then stat cards, then the breakdown. */
export const OEEScene: React.FC = () => (
  <AbsoluteFill>
    <AppFrame route="/oee">
      <PanZoom
        moves={[
          { at: 0, scale: 1.0, focusX: 960, focusY: 500 },
          { at: 45, scale: 1.0, focusX: 960, focusY: 500 },
          { at: 62, scale: 1.25, focusX: 700, focusY: 200 },
          { at: 85, scale: 1.25, focusX: 700, focusY: 200 },
          { at: 100, scale: 1.15, focusX: 860, focusY: 660 },
          { at: 120, scale: 1.15, focusX: 860, focusY: 700 },
          { at: 136, scale: 1.0, focusX: 960, focusY: 500 },
          { at: 152, scale: 1.0, focusX: 960, focusY: 500 },
        ]}
      >
        <OEE />
        {/* the degraded CNC-spindle row (61% OEE) */}
        <Highlight x={14} y={860} w={1620} h={102} inAt={102} outAt={122} />
      </PanZoom>
      <NavDrawer
        activePath="/oee"
        targetPath="/logistics/transportation"
        inAt={140}
        clickAt={158}
      />
    </AppFrame>
    <Caption
      text="Patterns you didn't know existed — surfaced by the correlation engine in seconds."
      accent="Patterns you didn't know existed"
      inAt={10}
      outAt={88}
    />
  </AbsoluteFill>
);
