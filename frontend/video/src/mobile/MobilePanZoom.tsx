import React from 'react';
import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { M_VIEW_W, M_VIEW_H, PAGE_W } from './theme';
import { PanZoomMove } from '../components/PanZoom';

interface MobilePanZoomProps {
  moves: PanZoomMove[];
  entrance?: boolean;
  children: React.ReactNode;
  /** Viewport override (stage px) — defaults to the full-bleed portrait view */
  viewW?: number;
  viewH?: number;
}

const EASE = Easing.bezier(0.3, 0, 0.12, 1);

/**
 * Portrait camera over a desktop-width (1920px) page. Focus coordinates are
 * page coordinates — identical to the desktop scenes. Horizontally the camera
 * clamps to the page edges (or centers the page when it is narrower than the
 * viewport, i.e. scale < 0.5625); vertically it is unclamped so zoomed-out
 * poses letterbox on the frame background by design.
 */
export const MobilePanZoom: React.FC<MobilePanZoomProps> = ({
  moves,
  entrance = true,
  children,
  viewW = M_VIEW_W,
  viewH = M_VIEW_H,
}) => {
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

  const entranceProgress = entrance
    ? spring({ frame, fps, config: { damping: 16, stiffness: 140 }, durationInFrames: 16 })
    : 1;
  const entranceScale = interpolate(entranceProgress, [0, 1], [1.04, 1]);

  const s = scale * entranceScale;
  const contentW = PAGE_W * s;
  const rawTx = viewW / 2 - focusX * s;
  const tx =
    contentW <= viewW
      ? (viewW - contentW) / 2
      : Math.min(0, Math.max(viewW - contentW, rawTx));
  const ty = viewH / 2 - focusY * s;

  return (
    <div
      style={{
        position: 'relative',
        width: PAGE_W,
        height: '100%',
        transform: `translate(${tx}px, ${ty}px) scale(${s})`,
        transformOrigin: '0 0',
      }}
    >
      {children}
    </div>
  );
};
