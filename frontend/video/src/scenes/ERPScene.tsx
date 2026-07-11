import React from 'react';
import { AbsoluteFill } from 'remotion';
import ERPIntegrationsPage from '../../../src/pages/erp/ERPIntegrations';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { Highlight } from '../components/Interactions';
import { NavDrawer } from '../components/NavDrawer';

/** Chain scene (financials → client): full page, then SAP + NetSuite punches. */
export const ERPScene: React.FC = () => (
  <AbsoluteFill>
    <AppFrame route="/erp">
      <PanZoom
        moves={[
          { at: 0, scale: 1.0, focusX: 960, focusY: 400 },
          { at: 45, scale: 1.0, focusX: 960, focusY: 400 },
          { at: 62, scale: 1.5, focusX: 620, focusY: 130 },
          { at: 88, scale: 1.5, focusX: 620, focusY: 130 },
          { at: 98, scale: 1.5, focusX: 620, focusY: 240 },
          { at: 112, scale: 1.5, focusX: 620, focusY: 240 },
          { at: 126, scale: 1.0, focusX: 960, focusY: 400 },
          { at: 140, scale: 1.0, focusX: 960, focusY: 400 },
        ]}
      >
        <ERPIntegrationsPage />
        {/* live-sync cards for both integrations */}
        <Highlight x={20} y={100} w={940} h={132} inAt={64} outAt={86} />
        <Highlight x={20} y={246} w={940} h={112} inAt={98} outAt={114} />
      </PanZoom>
      <NavDrawer activePath="/erp" targetPath="/kanban" inAt={128} clickAt={146} />
    </AppFrame>
    <Caption
      text="SAP and NetSuite, synced live — financials joined to the same correlation engine."
      accent="financials"
      inAt={10}
      outAt={90}
    />
  </AbsoluteFill>
);
