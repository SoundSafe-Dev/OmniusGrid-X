import React from 'react';
import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';

/**
 * Ghost-context element isolation for the portrait edition. Rendered INSIDE
 * MobilePanZoom (page coordinates, zooms with the camera): four frosted
 * panels dim + blur everything around the target rect, so the enlarged
 * element stays a visibly-cut piece of the big desktop screen — never a
 * reflowed mobile layout. The rect gets a subtle white ring + deep shadow
 * ("lifted"); the blue Highlight ring stays reserved for feature callouts
 * and can be layered inside a lift.
 */

export interface LiftRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface LiftFocusProps extends LiftRect {
  inAt: number;
  outAt: number;
  radius?: number;
  /** Softly dissolve one edge instead of ringing it (wide desktop rows) */
  fadeEdge?: 'right' | 'left' | 'none';
  /** Tween the rect to a second pose (e.g. widen when a popover opens) */
  to?: LiftRect & { at: number };
}

const EASE = Easing.bezier(0.3, 0, 0.12, 1);
const SCRIM = 'rgba(10,10,10,0.55)';
const FADE_W = 140;
const BIG = 8000;

export const LiftFocus: React.FC<LiftFocusProps> = ({
  x,
  y,
  w,
  h,
  inAt,
  outAt,
  radius = 14,
  fadeEdge = 'none',
  to,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame < inAt || frame > outAt + 10) return null;

  const enter = spring({
    frame: frame - inAt,
    fps,
    config: { damping: 15, stiffness: 140 },
    durationInFrames: 16,
  });
  const exit = interpolate(frame, [outAt, outAt + 10], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = Math.min(enter * 1.4, 1) * (1 - exit);

  // Optional rect tween (12 frames, eased)
  const t = to
    ? interpolate(frame, [to.at, to.at + 12], [0, 1], {
        easing: EASE,
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      })
    : 0;
  const rx = to ? interpolate(t, [0, 1], [x, to.x]) : x;
  const ry = to ? interpolate(t, [0, 1], [y, to.y]) : y;
  const rw = to ? interpolate(t, [0, 1], [w, to.w]) : w;
  const rh = to ? interpolate(t, [0, 1], [h, to.h]) : h;

  const panel: React.CSSProperties = {
    position: 'absolute',
    background: SCRIM,
    backdropFilter: 'blur(7px) saturate(0.8)',
    WebkitBackdropFilter: 'blur(7px) saturate(0.8)',
    opacity,
  };

  const ringMask =
    fadeEdge === 'right'
      ? 'linear-gradient(90deg, black 70%, transparent 99%)'
      : fadeEdge === 'left'
        ? 'linear-gradient(270deg, black 70%, transparent 99%)'
        : undefined;

  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 18 }}>
      {/* frosted surroundings */}
      <div style={{ ...panel, left: -BIG, top: -BIG, width: BIG * 2.5, height: BIG + ry }} />
      <div style={{ ...panel, left: -BIG, top: ry + rh, width: BIG * 2.5, height: BIG }} />
      <div style={{ ...panel, left: -BIG, top: ry, width: BIG + rx, height: rh }} />
      <div style={{ ...panel, left: rx + rw, top: ry, width: BIG, height: rh }} />
      {/* fade strip inside the dissolving edge */}
      {fadeEdge !== 'none' ? (
        <div
          style={{
            position: 'absolute',
            left: fadeEdge === 'right' ? rx + rw - FADE_W : rx,
            top: ry,
            width: FADE_W,
            height: rh,
            background: `linear-gradient(${fadeEdge === 'right' ? '90deg' : '270deg'}, rgba(10,10,10,0), ${SCRIM})`,
            opacity,
          }}
        />
      ) : null}
      {/* lifted ring + shadow */}
      <div
        style={{
          position: 'absolute',
          left: rx - 2,
          top: ry - 2,
          width: rw + 4,
          height: rh + 4,
          borderRadius: radius,
          border: '2px solid rgba(255,255,255,0.5)',
          boxShadow: '0 30px 90px rgba(0,0,0,0.5)',
          opacity,
          maskImage: ringMask,
          WebkitMaskImage: ringMask,
        }}
      />
    </div>
  );
};
