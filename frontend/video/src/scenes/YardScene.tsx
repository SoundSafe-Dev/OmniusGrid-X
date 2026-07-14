import React from 'react';
import { YardManagement } from '../../../src/pages/logistics/YardManagement';
import { FramedScene } from '../components/FramedScene';
import { Cursor } from '../components/Interactions';
import { LiftFocus } from '../mobile/components/LiftFocus';
import { TabHover } from '../mobile/components/TabHover';
import { NavDrawer } from '../components/NavDrawer';

/**
 * Yard (YMS) as a framed feature page: full view → Detention Risk / Cost
 * cards (lifted) → the tab rail showcased with a cursor glide (Trailers ·
 * Yard Map · Dock Doors · Appointments · Detention) → the first trailer row
 * with its detention charge. Rects measured from card border lines.
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
      { at: 46, scale: 1.0, focusX: 960, focusY: 500 },
      // detention pair
      { at: 52, scale: 1.55, focusX: 1207, focusY: 116 },
      { at: 76, scale: 1.55, focusX: 1207, focusY: 118 },
      // the tab rail
      { at: 84, scale: 1.5, focusX: 480, focusY: 470 },
      { at: 122, scale: 1.5, focusX: 480, focusY: 472 },
      // first trailer row (docked, detention $0) panning to the charge column
      { at: 130, scale: 1.4, focusX: 705, focusY: 660 },
      { at: 156, scale: 1.4, focusX: 1100, focusY: 662 },
      { at: 164, scale: 1.0, focusX: 960, focusY: 500 },
      { at: 178, scale: 1.0, focusX: 960, focusY: 500 },
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
