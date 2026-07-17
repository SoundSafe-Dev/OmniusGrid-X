import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { theme } from '../theme';

interface CaptionProps {
  text: string;
  /** Substring of `text` to tint with the highlight color */
  accent?: string;
  /** Scene-local frame the caption enters */
  inAt?: number;
  /** Scene-local frame the caption starts leaving */
  outAt: number;
}

/**
 * Lower-third caption: springs up with a clipped reveal. Charcoal pill with
 * white type + accent bar — deliberately distinct from the light UI behind it.
 */
export const Caption: React.FC<CaptionProps> = ({ text, accent, inAt = 8, outAt }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = spring({
    frame: frame - inAt,
    fps,
    config: { damping: 15, stiffness: 130 },
    durationInFrames: 18,
  });
  const exit = interpolate(frame, [outAt, outAt + 10], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const y = interpolate(enter, [0, 1], [140, 0]) + exit * 100;
  const opacity = Math.min(enter * 1.4, 1) * (1 - exit);

  const renderText = () => {
    if (!accent) return text;
    const idx = text.indexOf(accent);
    if (idx === -1) return text;
    return (
      <>
        {text.slice(0, idx)}
        <span style={{ color: theme.highlightSoft, fontWeight: 700 }}>{accent}</span>
        {text.slice(idx + accent.length)}
      </>
    );
  };

  return (
    <div
      style={{
        position: 'absolute',
        left: 140,
        bottom: 140,
        maxWidth: 3580,
        transform: `translateY(${y}px)`,
        opacity,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'stretch',
          borderRadius: 24,
          overflow: 'hidden',
          boxShadow: '0 30px 90px rgba(0, 0, 0, 0.5)',
        }}
      >
        <div style={{ width: 16, background: theme.highlight }} />
        <div
          style={{
            padding: '44px 68px',
            background: 'rgba(10, 10, 10, 0.94)',
            fontFamily: theme.fontFamily,
            fontSize: 74,
            lineHeight: 1.28,
            whiteSpace: 'nowrap',
            fontWeight: 600,
            letterSpacing: 0.2,
            color: theme.darkText,
          }}
        >
          {renderText()}
        </div>
      </div>
    </div>
  );
};
