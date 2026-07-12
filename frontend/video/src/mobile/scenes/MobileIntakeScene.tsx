import React from 'react';
import { AbsoluteFill } from 'remotion';
import { IntakeInbox } from '../../../../src/pages/intake/IntakeInbox';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { MobileNavDrawer } from '../MobileNavDrawer';
import { LiftFocus } from '../components/LiftFocus';
import { M_FULL } from '../theme';

/** Portrait intake: full inbox, then punch on the analyzed Q3 card. */
export const MobileIntakeScene: React.FC = () => (
  <AbsoluteFill>
    <MobileAppFrame route="/intake">
      <MobilePanZoom
        moves={[
          { at: 0, ...M_FULL },
          { at: 45, ...M_FULL },
          // Q3 card lifted large — hold on the left cluster (title, risk,
          // the anomaly-cluster analysis); the right side is empty space
          { at: 58, scale: 1.25, focusX: 455, focusY: 790 },
          { at: 80, scale: 1.25, focusX: 480, focusY: 802 },
          { at: 98, ...M_FULL },
          { at: 112, ...M_FULL },
        ]}
      >
        <IntakeInbox />
        {/* the Q3 Production Log card — analyzed multi-tab spreadsheet */}
        <LiftFocus x={26} y={670} w={1454} h={256} inAt={58} outAt={86} />
      </MobilePanZoom>
      <MobileNavDrawer activePath="/intake" targetPath="/assets" inAt={104} clickAt={124} />
    </MobileAppFrame>
    <MobileCaption
      text="Spreadsheets, PDFs, photos, audio, video — every format becomes correlated data on arrival."
      accent="every format"
      inAt={10}
      outAt={88}
    />
  </AbsoluteFill>
);
