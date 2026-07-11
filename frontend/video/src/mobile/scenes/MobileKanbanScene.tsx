import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Check } from 'lucide-react';
import Kanban from '../../../../src/pages/Kanban';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { MobileNavDrawer } from '../MobileNavDrawer';
import { Cursor } from '../../components/Interactions';
import { LiftFocus } from '../components/LiftFocus';
import { theme } from '../../theme';
import { M_FULL } from '../theme';

/**
 * Portrait Kanban with the task-assignment interaction — replica popover,
 * assignee-chip swap and toast at the same page coordinates as desktop; one
 * held portrait camera keeps card + popover + toast in frame throughout.
 */

const PICK_OPEN = 108;
const PICK_AT = 128;
const POP_OUT = 136;
const TOAST_IN = 138;
const TOAST_OUT = 172;

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
  const hover = frame >= PICK_AT - 8;
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

export const MobileKanbanScene: React.FC = () => (
  <AbsoluteFill>
    <MobileAppFrame route="/kanban">
      <MobilePanZoom
        moves={[
          { at: 0, ...M_FULL },
          { at: 50, ...M_FULL },
          // WO-4482 card lifted big, then the window widens for the popover
          { at: 68, scale: 2.0, focusX: 850, focusY: 386 },
          { at: 100, scale: 2.0, focusX: 850, focusY: 386 },
          { at: 112, scale: 1.35, focusX: 990, focusY: 520 },
          { at: 170, scale: 1.35, focusX: 990, focusY: 525 },
          { at: 186, ...M_FULL },
          { at: 202, ...M_FULL },
        ]}
      >
        <Kanban />
        <LiftFocus
          x={694}
          y={278}
          w={312}
          h={216}
          inAt={72}
          outAt={176}
          to={{ at: 104, x: 640, y: 270, w: 700, h: 510 }}
        />
        <AssignPopover />
        <AssigneeSwap />
        <AssignToast />
        <Cursor
          path={[
            { at: 78, x: 400, y: 600 },
            { at: 96, x: 750, y: 440 },
            { at: 110, x: 750, y: 440 },
            { at: 120, x: 1110, y: 513 },
            { at: 134, x: 1110, y: 513 },
            { at: 156, x: 1250, y: 640 },
          ]}
          clicks={[102, PICK_AT]}
          inAt={74}
          outAt={176}
        />
      </MobilePanZoom>
      <MobileNavDrawer activePath="/kanban" targetPath="/nlp" inAt={186} clickAt={204} />
    </MobileAppFrame>
    <MobileCaption
      text="One incident, four departments — work assigned to each, against shared goals."
      accent="four departments"
      inAt={10}
      outAt={94}
    />
  </AbsoluteFill>
);
