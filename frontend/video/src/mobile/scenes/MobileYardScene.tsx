import React from 'react';
import { YardManagement } from '../../../../src/pages/logistics/YardManagement';
import { MobileFramedScene } from '../MobileFramedScene';
import { LiftFocus } from '../components/LiftFocus';
import { NavDrawer } from '../../components/NavDrawer';

/** Portrait YMS: stacked framed layout, desktop MiniStage internals. */
export const MobileYardScene: React.FC = () => (
  <MobileFramedScene
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
      // portrait-window cameras (viewport 1064x906, fit-width 0.554)
      { at: 0, scale: 0.554, focusX: 960, focusY: 650 },
      { at: 52, scale: 0.554, focusX: 960, focusY: 650 },
      { at: 68, scale: 1.9, focusX: 1205, focusY: 130 },
      { at: 90, scale: 1.9, focusX: 1205, focusY: 132 },
      { at: 104, scale: 0.83, focusX: 800, focusY: 620 },
      { at: 120, scale: 0.83, focusX: 1050, focusY: 650 },
      { at: 134, scale: 0.554, focusX: 960, focusY: 650 },
      { at: 148, scale: 0.554, focusX: 960, focusY: 650 },
    ]}
    overlays={
      <LiftFocus x={955} y={84} w={500} h={92} inAt={70} outAt={96} radius={12} />
    }
    stageOverlay={
      <NavDrawer activePath="/logistics/yard" targetPath="/erp" inAt={138} clickAt={152} />
    }
  />
);
