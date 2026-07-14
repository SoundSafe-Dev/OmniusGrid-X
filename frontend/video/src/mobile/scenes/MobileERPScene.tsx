import React from 'react';
import { AbsoluteFill } from 'remotion';
import ERPIntegrationsPage from '../../../../src/pages/erp/ERPIntegrations';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { MobileNavDrawer } from '../MobileNavDrawer';
import { LiftFocus } from '../components/LiftFocus';
import { M_FULL } from '../theme';

/**
 * Portrait ERP: the ghost-lift steps down all seven live ERP connectors —
 * SAP S/4HANA, NetSuite, Oracle Fusion, Dynamics 365, Odoo, Infor
 * CloudSuite, Epicor Kinetic. Same card rects and beat times as desktop.
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
  { at: a, scale: 1.1, focusX: 490, focusY: CARD_TOPS[i] + 64 },
  { at: b, scale: 1.1, focusX: 490, focusY: CARD_TOPS[i] + 64 },
]);

export const MobileERPScene: React.FC = () => (
  <AbsoluteFill>
    <MobileAppFrame route="/erp">
      <MobilePanZoom
        moves={[
          { at: 0, ...M_FULL },
          { at: 48, ...M_FULL },
          ...CAMERA,
          { at: 172, ...M_FULL },
          { at: 186, ...M_FULL },
        ]}
      >
        <ERPIntegrationsPage />
        <LiftFocus x={20} y={95} w={940} h={139} steps={STEPS} inAt={54} outAt={166} radius={10} />
      </MobilePanZoom>
      <MobileNavDrawer activePath="/erp" targetPath="/kanban" inAt={180} clickAt={198} />
    </MobileAppFrame>
    <MobileCaption
      text="SAP, Oracle, NetSuite, Dynamics, Odoo, Infor, Epicor — every ERP, synced live."
      accent="every ERP"
      inAt={10}
      outAt={150}
    />
  </AbsoluteFill>
);
