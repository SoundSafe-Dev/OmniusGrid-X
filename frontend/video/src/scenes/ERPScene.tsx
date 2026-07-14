import React from 'react';
import { AbsoluteFill } from 'remotion';
import ERPIntegrationsPage from '../../../src/pages/erp/ERPIntegrations';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { LiftFocus } from '../mobile/components/LiftFocus';
import { NavDrawer } from '../components/NavDrawer';

/**
 * Chain scene (financials → client): full page, then the ghost-lift steps
 * down all seven live ERP connectors — SAP S/4HANA, NetSuite, Oracle Fusion,
 * Dynamics 365, Odoo, Infor CloudSuite, Epicor Kinetic. Card tops measured
 * from border lines: 100 + 146·k, ~129 tall.
 */

const CARD_TOPS = [100, 246, 392, 538, 684, 830, 976];
const STEP_TIMES: [number, number][] = [
  [54, 62],
  [70, 78],
  [86, 94],
  [102, 110],
  [118, 126],
  [134, 142],
  [150, 160],
];

const rectAt = (i: number) => ({ x: 20, y: CARD_TOPS[i] - 5, w: 940, h: 139 });

const STEPS = STEP_TIMES.flatMap(([a, b], i) => [
  { at: a, ...rectAt(i) },
  { at: b, ...rectAt(i) },
]);

const CAMERA = STEP_TIMES.flatMap(([a, b], i) => [
  { at: a, scale: 1.13, focusX: 490, focusY: CARD_TOPS[i] + 64 },
  { at: b, scale: 1.13, focusX: 490, focusY: CARD_TOPS[i] + 64 },
]);

export const ERPScene: React.FC = () => (
  <AbsoluteFill>
    <AppFrame route="/erp">
      <PanZoom
        moves={[
          { at: 0, scale: 1.0, focusX: 960, focusY: 400 },
          { at: 48, scale: 1.0, focusX: 960, focusY: 400 },
          ...CAMERA,
          { at: 172, scale: 1.0, focusX: 960, focusY: 400 },
          { at: 186, scale: 1.0, focusX: 960, focusY: 400 },
        ]}
      >
        <ERPIntegrationsPage />
        <LiftFocus x={20} y={95} w={940} h={139} steps={STEPS} inAt={54} outAt={166} radius={10} />
      </PanZoom>
      <NavDrawer activePath="/erp" targetPath="/kanban" inAt={180} clickAt={198} />
    </AppFrame>
    <Caption
      text="SAP, Oracle, NetSuite, Dynamics, Odoo, Infor, Epicor — every ERP, synced live."
      accent="every ERP"
      inAt={10}
      outAt={150}
    />
  </AbsoluteFill>
);
