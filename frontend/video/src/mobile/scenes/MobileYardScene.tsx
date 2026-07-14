import React from 'react';
import { YardManagement } from '../../../../src/pages/logistics/YardManagement';
import { MobileFramedScene } from '../MobileFramedScene';
import { Cursor } from '../../components/Interactions';
import { LiftFocus } from '../components/LiftFocus';
import { TabHover } from '../components/TabHover';
import { NavDrawer } from '../../components/NavDrawer';

/**
 * Portrait YMS: full tall page → Detention Risk / Cost cards → the tab rail
 * showcased with a cursor glide + real hover reactions → the first trailer
 * row with its detention charge. Same beats and page rects as desktop.
 */
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
      { at: 46, scale: 0.554, focusX: 960, focusY: 650 },
      // detention pair
      { at: 52, scale: 1.9, focusX: 1207, focusY: 116 },
      { at: 76, scale: 1.9, focusX: 1207, focusY: 118 },
      // the tab rail
      { at: 84, scale: 0.97, focusX: 545, focusY: 470 },
      { at: 122, scale: 0.97, focusX: 545, focusY: 472 },
      // first trailer row panning to the charge column
      { at: 130, scale: 0.83, focusX: 660, focusY: 655 },
      { at: 156, scale: 0.83, focusX: 880, focusY: 658 },
      { at: 164, scale: 0.554, focusX: 960, focusY: 650 },
      { at: 178, scale: 0.554, focusX: 960, focusY: 650 },
    ]}
    overlays={
      <>
        {/* Detention Risk + Detention Cost cards — "before they bill" */}
        <LiftFocus x={962} y={74} w={490} h={84} inAt={52} outAt={78} radius={12} />
        {/* tab rail: Trailers … Detention, hovered tab reacts for real */}
        <LiftFocus x={14} y={448} w={660} h={44} inAt={86} outAt={124} radius={10} />
        <TabHover
          steps={[
            { at: 90, index: 1 },
            { at: 98, index: 2 },
            { at: 106, index: 3 },
            { at: 114, index: 4 },
            { at: 122, index: 5 },
          ]}
          until={126}
        />
        <Cursor
          path={[
            { at: 90, x: 79, y: 464 },
            { at: 98, x: 185, y: 464 },
            { at: 106, x: 317, y: 464 },
            { at: 114, x: 470, y: 464 },
            { at: 122, x: 613, y: 464 },
          ]}
          inAt={88}
          outAt={126}
        />
        {/* first trailer row */}
        <LiftFocus x={14} y={620} w={1580} h={66} inAt={130} outAt={158} fadeEdge="right" radius={10} />
      </>
    }
    stageOverlay={
      <NavDrawer activePath="/logistics/yard" targetPath="/erp" inAt={170} clickAt={188} />
    }
  />
);
