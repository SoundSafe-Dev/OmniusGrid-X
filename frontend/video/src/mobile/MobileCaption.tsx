import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { theme } from '../theme';

interface MobileCaptionProps {
  text: string;
  accent?: string;
  inAt?: number;
  outAt: number;
}

/**
 * Portrait lower-third: same charcoal pill as the desktop caption, sized for
 * the 2160-wide canvas and centered in the bottom letterbox band.
 */
export const MobileCaption: React.FC<MobileCaptionProps> = ({ text, accent, inAt = 8, outAt }) => {
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
        left: 90,
        right: 90,
        bottom: 260,
        display: 'flex',
        justifyContent: 'center',
        transform: `translateY(${y}px)`,
        opacity,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'stretch',
          borderRadius: 22,
          overflow: 'hidden',
          boxShadow: '0 30px 90px rgba(0, 0, 0, 0.5)',
        }}
      >
        <div style={{ width: 12, background: theme.highlight }} />
        <div
          style={{
            padding: '32px 48px',
            background: 'rgba(10, 10, 10, 0.94)',
            fontFamily: theme.fontFamily,
            fontSize: 60,
            lineHeight: 1.3,
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
