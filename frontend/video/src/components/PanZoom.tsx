import React from 'react';
import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { STAGE_W, STAGE_H, CHROME_H } from '../theme';

export interface PanZoomMove {
  /** Frame (scene-local) at which this keyframe applies */
  at: number;
  /** Zoom factor, >= 1 so edges never show */
  scale: number;
  /** Stage-coordinate point to center in the viewport */
  focusX: number;
  focusY: number;
}

interface PanZoomProps {
  moves: PanZoomMove[];
  /** Spring-in with a slight overshoot on scene entry */
  entrance?: boolean;
  children: React.ReactNode;
}

const VIEW_W = STAGE_W;
const VIEW_H = STAGE_H - CHROME_H;

// Punchy but smooth: fast acceleration, long settle
const EASE = Easing.bezier(0.3, 0, 0.12, 1);

/**
 * Ken Burns / punch-in camera for a page mounted in the AppFrame stage.
 * Keyframes are interpolated with an eased curve; consecutive keyframes with
 * an 8-12 frame gap read as the "punch-in" signature move, wide gaps read
 * as slow drift.
 */
export const PanZoom: React.FC<PanZoomProps> = ({ moves, entrance = true, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const times = moves.map((m) => m.at);
  const opts = {
    easing: EASE,
    extrapolateLeft: 'clamp' as const,
    extrapolateRight: 'clamp' as const,
  };

  const scale =
    moves.length > 1
      ? interpolate(frame, times, moves.map((m) => m.scale), opts)
      : moves[0].scale;
  const focusX =
    moves.length > 1
      ? interpolate(frame, times, moves.map((m) => m.focusX), opts)
      : moves[0].focusX;
  const focusY =
    moves.length > 1
      ? interpolate(frame, times, moves.map((m) => m.focusY), opts)
      : moves[0].focusY;

  // Entrance: overshoot from 1.06x down to 1x over ~14 frames
  const entranceProgress = entrance
    ? spring({ frame, fps, config: { damping: 16, stiffness: 140 }, durationInFrames: 16 })
    : 1;
  const entranceScale = interpolate(entranceProgress, [0, 1], [1.06, 1]);

  const s = scale * entranceScale;
  const tx = VIEW_W / 2 - focusX * s;
  const ty = VIEW_H / 2 - focusY * s;

  // Never let the camera show past the content edges (scale >= 1 guaranteed)
  const clampedTx = Math.min(0, Math.max(VIEW_W - STAGE_W * s, tx));
  const clampedTy = Math.min(0, ty);

  return (
    <div
      style={{
        position: 'relative',
        width: STAGE_W,
        // Full height so percentage-height pages (fitHeight) resolve correctly;
        // taller pages simply overflow visibly and the camera pans over them.
        height: '100%',
        transform: `translate(${clampedTx}px, ${clampedTy}px) scale(${s})`,
        transformOrigin: '0 0',
      }}
    >
      {children}
    </div>
  );
};
