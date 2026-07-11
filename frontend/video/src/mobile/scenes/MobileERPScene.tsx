import React from 'react';
import { AbsoluteFill } from 'remotion';
import ERPIntegrationsPage from '../../../../src/pages/erp/ERPIntegrations';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { MobileNavDrawer } from '../MobileNavDrawer';
import { LiftFocus } from '../components/LiftFocus';
import { M_FULL } from '../theme';

/** Portrait ERP: SAP + NetSuite live-sync card punches. */
export const MobileERPScene: React.FC = () => (
  <AbsoluteFill>
    <MobileAppFrame route="/erp">
      <MobilePanZoom
        moves={[
          { at: 0, ...M_FULL },
          { at: 45, ...M_FULL },
          // SAP card lift, then NetSuite — whole card fits at 1.13x
          { at: 62, scale: 1.13, focusX: 490, focusY: 166 },
          { at: 86, scale: 1.13, focusX: 490, focusY: 168 },
          { at: 98, scale: 1.13, focusX: 490, focusY: 302 },
          { at: 112, scale: 1.13, focusX: 490, focusY: 302 },
          { at: 126, ...M_FULL },
          { at: 140, ...M_FULL },
        ]}
      >
        <ERPIntegrationsPage />
        <LiftFocus x={20} y={100} w={940} h={132} inAt={62} outAt={88} radius={10} />
        <LiftFocus x={20} y={246} w={940} h={112} inAt={96} outAt={114} radius={10} />
      </MobilePanZoom>
      <MobileNavDrawer activePath="/erp" targetPath="/kanban" inAt={128} clickAt={146} />
    </MobileAppFrame>
    <MobileCaption
      text="SAP and NetSuite, synced live — financials joined to the same correlation engine."
      accent="financials"
      inAt={10}
      outAt={90}
    />
  </AbsoluteFill>
);
