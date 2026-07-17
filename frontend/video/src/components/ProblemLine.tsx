import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { theme } from '../theme';

/**
 * Cold open on the problem, monochrome: white statement on charcoal with the
 * pain phrase snapping in as an inverted (white) pill.
 */
export const ProblemLine: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const textIn = spring({
    frame: frame - 4,
    fps,
    config: { damping: 16, stiffness: 120 },
    durationInFrames: 20,
  });
  const pillIn = spring({
    frame: frame - 26,
    fps,
    config: { damping: 11, stiffness: 150 },
    durationInFrames: 20,
  });
  const out = interpolate(frame, [86, 96], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        background: theme.darkBg,
        fontFamily: theme.fontFamily,
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 34,
          opacity: Math.min(textIn * 1.3, 1) * out,
          transform: `translateY(${interpolate(textIn, [0, 1], [40, 0])}px)`,
          flexWrap: 'wrap',
          justifyContent: 'center',
          padding: '0 200px',
        }}
      >
        <span
          style={{
            fontSize: 92,
            fontWeight: 600,
            color: theme.darkText,
            letterSpacing: -1,
            whiteSpace: 'nowrap',
          }}
        >
          You cannot make smart decisions with
        </span>
        <span
          style={{
            display: 'inline-block',
            transform: `scale(${interpolate(pillIn, [0, 1], [0.6, 1])})`,
            opacity: Math.min(pillIn * 1.4, 1),
            background: theme.darkText,
            color: theme.darkBg,
            fontSize: 92,
            fontWeight: 800,
            letterSpacing: -1,
            padding: '10px 54px 22px',
            borderRadius: 32,
            boxShadow: '0 0 80px rgba(250,250,250,0.28)',
            whiteSpace: 'nowrap',
          }}
        >
          scattered data
        </span>
      </div>
    </AbsoluteFill>
  );
};
