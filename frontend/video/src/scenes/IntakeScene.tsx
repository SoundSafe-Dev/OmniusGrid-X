import React from 'react';
import { AbsoluteFill } from 'remotion';
import { IntakeInbox } from '../../../src/pages/intake/IntakeInbox';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { Highlight } from '../components/Interactions';
import { NavDrawer } from '../components/NavDrawer';

/** Source scene: full inbox first, then cascade down the multi-format items. */
export const IntakeScene: React.FC = () => (
  <AbsoluteFill>
    <AppFrame route="/intake">
      <PanZoom
        moves={[
          { at: 0, scale: 1.0, focusX: 960, focusY: 518 },
          { at: 45, scale: 1.0, focusX: 960, focusY: 518 },
          { at: 58, scale: 1.27, focusX: 720, focusY: 700 },
          { at: 80, scale: 1.27, focusX: 720, focusY: 800 },
          { at: 98, scale: 1.0, focusX: 960, focusY: 518 },
          { at: 112, scale: 1.0, focusX: 960, focusY: 518 },
        ]}
      >
        <IntakeInbox />
        {/* the Q3 Production Log card — analyzed multi-tab spreadsheet */}
        <Highlight x={26} y={670} w={1454} h={256} inAt={60} outAt={84} radius={14} />
      </PanZoom>
      <NavDrawer activePath="/intake" targetPath="/assets" inAt={104} clickAt={124} />
    </AppFrame>
    <Caption
      text="Spreadsheets, PDFs, photos, audio, video — every format becomes correlated data on arrival."
      accent="every format"
      inAt={10}
      outAt={88}
    />
  </AbsoluteFill>
);
