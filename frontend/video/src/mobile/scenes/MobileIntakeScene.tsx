import React from 'react';
import { AbsoluteFill } from 'remotion';
import { IntakeInbox } from '../../../../src/pages/intake/IntakeInbox';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { MobileNavDrawer } from '../MobileNavDrawer';
import { LiftFocus } from '../components/LiftFocus';
import { M_FULL } from '../theme';

/**
 * Portrait intake: full inbox, then the lift steps item by item down the
 * multi-format list — spreadsheet, PDF, whiteboard photo, SAP export, audio
 * sample, dock-camera video. Item bounds measured from card border lines:
 * tops at 684 / 948 / 1194 / 1441 / 1688 / 1935, ~234 tall, x 26..1480.
 */

const ITEM_TOPS = [656, 920, 1166, 1413, 1660, 1907];
// the last item is still "analyzing" — its card has no risk/analysis section
const ITEM_HEIGHTS = [247, 247, 247, 247, 247, 117];
const STEP_TIMES: [number, number][] = [
  [50, 58],
  [64, 72],
  [78, 86],
  [92, 100],
  [106, 114],
  [120, 130],
];

const rectAt = (i: number) => ({
  x: 26,
  y: ITEM_TOPS[i] - 6,
  w: 1462,
  h: ITEM_HEIGHTS[i],
});

const STEPS = STEP_TIMES.flatMap(([a, b], i) => [
  { at: a, ...rectAt(i) },
  { at: b, ...rectAt(i) },
]);

const CAMERA = STEP_TIMES.flatMap(([a, b], i) => [
  { at: a, scale: 1.25, focusX: 455, focusY: ITEM_TOPS[i] + ITEM_HEIGHTS[i] / 2 },
  { at: b, scale: 1.25, focusX: 455, focusY: ITEM_TOPS[i] + ITEM_HEIGHTS[i] / 2 },
]);

export const MobileIntakeScene: React.FC = () => (
  <AbsoluteFill>
    <MobileAppFrame route="/intake">
      <MobilePanZoom
        moves={[
          { at: 0, ...M_FULL },
          { at: 44, ...M_FULL },
          ...CAMERA,
          { at: 136, ...M_FULL },
          { at: 150, ...M_FULL },
        ]}
      >
        <IntakeInbox />
        <LiftFocus x={26} y={678} w={1462} h={247} steps={STEPS} inAt={50} outAt={134} />
      </MobilePanZoom>
      <MobileNavDrawer activePath="/intake" targetPath="/assets" inAt={140} clickAt={158} />
    </MobileAppFrame>
    <MobileCaption
      text="Spreadsheets, PDFs, photos, audio, video — every format becomes correlated data on arrival."
      accent="every format"
      inAt={10}
      outAt={116}
    />
  </AbsoluteFill>
);
