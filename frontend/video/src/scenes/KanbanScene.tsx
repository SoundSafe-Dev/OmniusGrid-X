import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Check } from 'lucide-react';
import Kanban from '../../../src/pages/Kanban';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { Cursor } from '../components/Interactions';
import { LiftFocus } from '../mobile/components/LiftFocus';
import { NavDrawer } from '../components/NavDrawer';
import { theme } from '../theme';

/**
 * Multi-departmental action: full board, the WO-4482 card lifts, then the
 * cursor assigns the task — picker popover, R. Okafor picked (check), the
 * card's assignee chip flips, and a confirmation toast lands. Frame-driven
 * replica UI (same Tailwind vocabulary as the app), no component state.
 */

const CHIP_CLICK = 124;
const PICK_OPEN = 130; // popover opens
const PICK_AT = 152; // member row clicked
const POP_OUT = 160;
const TOAST_IN = 162;
const TOAST_OUT = 204;

const MEMBERS = [
  { initials: 'DA', name: 'Dev Admin', role: 'Operations' },
  { initials: 'RO', name: 'R. Okafor', role: 'Maintenance' },
  { initials: 'SL', name: 'S. Lindqvist', role: 'Quality' },
];

const AssignPopover: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame < PICK_OPEN || frame > POP_OUT + 6) return null;

  const enter = spring({
    frame: frame - PICK_OPEN,
    fps,
    config: { damping: 15, stiffness: 170 },
    durationInFrames: 12,
  });
  const exit = interpolate(frame, [POP_OUT, POP_OUT + 6], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const hover = frame >= PICK_AT - 10;
  const picked = frame >= PICK_AT;

  return (
    <div
      style={{
        position: 'absolute',
        left: 1022,
        top: 392,
        width: 300,
        zIndex: 35,
        opacity: Math.min(enter * 1.4, 1) * (1 - exit),
        transform: `translateY(${interpolate(enter, [0, 1], [10, 0])}px) scale(${interpolate(enter, [0, 1], [0.96, 1])})`,
        transformOrigin: 'top left',
      }}
    >
      <div className="bg-white border border-gray-200 shadow-lg rounded-lg overflow-hidden">
        <div className="px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide border-b border-gray-100">
          Assign to
        </div>
        {MEMBERS.map((m, i) => {
          const isTarget = i === 1;
          return (
            <div
              key={m.name}
              className={`flex items-center gap-3 px-4 py-2.5 ${
                isTarget && hover ? 'bg-gray-100' : 'bg-white'
              }`}
            >
              <div
                className="flex items-center justify-center rounded-full text-white text-xs font-semibold"
                style={{
                  width: 30,
                  height: 30,
                  background: isTarget ? theme.highlight : '#8b5cf6',
                }}
              >
                {m.initials}
              </div>
              <div style={{ flex: 1 }}>
                <div className="text-sm font-medium text-gray-900">{m.name}</div>
                <div className="text-xs text-gray-500">{m.role}</div>
              </div>
              {isTarget && picked ? <Check className="w-4 h-4 text-green-500" /> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const CHIP = { x: 705, y: 427, w: 100, h: 27 };
const AssigneeSwap: React.FC = () => {
  const frame = useCurrentFrame();
  if (frame < PICK_AT + 4) return null;
  return (
    <div
      style={{
        position: 'absolute',
        left: CHIP.x,
        top: CHIP.y,
        width: CHIP.w,
        height: CHIP.h,
        zIndex: 25,
        background: '#ffffff',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <div
        className="flex items-center justify-center rounded-full text-white font-semibold"
        style={{ width: 20, height: 20, fontSize: 9, background: theme.highlight, flexShrink: 0 }}
      >
        RO
      </div>
      <span style={{ whiteSpace: 'nowrap', fontSize: 12, color: '#374151' }}>R. Okafor</span>
    </div>
  );
};

const AssignToast: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame < TOAST_IN || frame > TOAST_OUT + 8) return null;

  const enter = spring({
    frame: frame - TOAST_IN,
    fps,
    config: { damping: 14, stiffness: 150 },
    durationInFrames: 14,
  });
  const exit = interpolate(frame, [TOAST_OUT, TOAST_OUT + 8], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div
      style={{
        position: 'absolute',
        left: 640,
        top: 700,
        zIndex: 35,
        opacity: Math.min(enter * 1.4, 1) * (1 - exit),
        transform: `translateY(${interpolate(enter, [0, 1], [24, 0])}px)`,
      }}
    >
      <div
        className="flex items-center gap-2.5 rounded-lg px-5 py-3 shadow-xl"
        style={{ background: 'rgba(10,10,10,0.94)' }}
      >
        <Check className="w-5 h-5 text-green-400" />
        <span className="text-sm font-medium text-white">
          WO-4482 assigned to R. Okafor — Maintenance
        </span>
      </div>
    </div>
  );
};

export const KanbanScene: React.FC = () => (
  <AbsoluteFill>
    <AppFrame route="/kanban">
      <PanZoom
        moves={[
          { at: 0, scale: 1.0, focusX: 960, focusY: 500 },
          { at: 58, scale: 1.0, focusX: 960, focusY: 500 },
          // WO-4482 card lifted big, then the window widens for the popover
          { at: 66, scale: 2.0, focusX: 860, focusY: 386 },
          { at: 114, scale: 2.0, focusX: 860, focusY: 386 },
          { at: 126, scale: 1.35, focusX: 990, focusY: 520 },
          { at: 204, scale: 1.35, focusX: 990, focusY: 525 },
          { at: 216, scale: 1.0, focusX: 960, focusY: 500 },
          { at: 236, scale: 1.0, focusX: 960, focusY: 500 },
        ]}
      >
        <Kanban />
        <LiftFocus
          x={694}
          y={278}
          w={312}
          h={216}
          inAt={70}
          outAt={212}
          to={{ at: 118, x: 640, y: 270, w: 700, h: 510 }}
        />
        <AssignPopover />
        <AssigneeSwap />
        <AssignToast />
        <Cursor
          path={[
            { at: 90, x: 400, y: 600 },
            { at: 108, x: 750, y: 440 },
            { at: 130, x: 750, y: 440 },
            { at: 144, x: 1110, y: 513 },
            { at: 164, x: 1110, y: 513 },
            { at: 188, x: 1250, y: 640 },
          ]}
          clicks={[CHIP_CLICK, PICK_AT]}
          inAt={86}
          outAt={214}
        />
      </PanZoom>
      <NavDrawer activePath="/kanban" targetPath="/nlp" inAt={222} clickAt={242} />
    </AppFrame>
    <Caption
      text="One incident, four departments — work assigned to each, against shared goals."
      accent="four departments"
      inAt={10}
      outAt={112}
    />
  </AbsoluteFill>
);
