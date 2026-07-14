import React from 'react';
import { AbsoluteFill } from 'remotion';
import { IntakeInbox } from '../../../src/pages/intake/IntakeInbox';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { NavDrawer } from '../components/NavDrawer';
import { LiftFocus } from '../mobile/components/LiftFocus';

/**
 * Source scene: full inbox first, then the ghost-lift steps item by item
 * down the multi-format list — spreadsheet, PDF, whiteboard photo, SAP
 * export, audio sample, dock-camera video. Item bounds from measured card
 * border lines (same page space as the mobile edition): tops at
 * 656 / 920 / 1166 / 1413 / 1660 / 1907, x 26..1488.
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
  { at: a, scale: 1.25, focusX: 755, focusY: ITEM_TOPS[i] + ITEM_HEIGHTS[i] / 2 },
  { at: b, scale: 1.25, focusX: 755, focusY: ITEM_TOPS[i] + ITEM_HEIGHTS[i] / 2 },
]);

export const IntakeScene: React.FC = () => (
  <AbsoluteFill>
    <AppFrame route="/intake">
      <PanZoom
        moves={[
          { at: 0, scale: 1.0, focusX: 960, focusY: 518 },
          { at: 44, scale: 1.0, focusX: 960, focusY: 518 },
          ...CAMERA,
          { at: 136, scale: 1.0, focusX: 960, focusY: 518 },
          { at: 150, scale: 1.0, focusX: 960, focusY: 518 },
        ]}
      >
        <IntakeInbox />
        <LiftFocus x={26} y={650} w={1462} h={247} steps={STEPS} inAt={50} outAt={134} />
      </PanZoom>
      <NavDrawer activePath="/intake" targetPath="/assets" inAt={140} clickAt={158} />
    </AppFrame>
    <Caption
      text="Spreadsheets, PDFs, photos, audio, video — every format becomes correlated data on arrival."
      accent="every format"
      inAt={10}
      outAt={116}
    />
  </AbsoluteFill>
);
