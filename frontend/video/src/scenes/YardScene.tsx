import React from 'react';
import { YardManagement } from '../../../src/pages/logistics/YardManagement';
import { FramedScene } from '../components/FramedScene';
import { Highlight } from '../components/Interactions';
import { NavDrawer } from '../components/NavDrawer';

/**
 * Yard (YMS) as a framed feature page: trailer inventory, dock doors,
 * detention risk. Opens fully visible, punches into the stats row and the
 * trailer table. Ends with a sidebar navigation to the Dashboard.
 */
export const YardScene: React.FC = () => (
  <FramedScene
    overline="Logistics · YMS"
    title="Yard Management"
    bullets={[
      'Every trailer, door and gate move — live',
      'Dwell times and detention alerts before they bill',
      'Dock-door capacity and today’s appointments',
    ]}
    route="/logistics/yard"
    page={<YardManagement />}
    moves={[
      { at: 0, scale: 1.0, focusX: 960, focusY: 500 },
      { at: 52, scale: 1.0, focusX: 960, focusY: 500 },
      { at: 68, scale: 1.15, focusX: 1150, focusY: 250 },
      { at: 90, scale: 1.15, focusX: 1180, focusY: 250 },
      { at: 104, scale: 1.18, focusX: 950, focusY: 620 },
      { at: 120, scale: 1.18, focusX: 950, focusY: 660 },
      { at: 134, scale: 1.0, focusX: 960, focusY: 500 },
      { at: 148, scale: 1.0, focusX: 960, focusY: 500 },
    ]}
    overlays={
      /* Detention Risk + Detention Cost cards — "before they bill" */
      <Highlight x={960} y={88} w={490} h={82} inAt={70} outAt={96} radius={12} />
    }
    stageOverlay={
      <NavDrawer activePath="/logistics/yard" targetPath="/erp" inAt={138} clickAt={152} />
    }
  />
);
