import React from 'react';
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import { theme } from '../theme';
import { Wordmark } from './Wordmark';

const LINES = ['Optimized Operations.', 'Actionable Insights.', 'Maximum Efficiency.'];

export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const logoIn = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 120 },
    durationInFrames: 20,
  });
  const byFade = interpolate(frame, [58, 76], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        background: theme.bg,
        fontFamily: theme.fontFamily,
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 44,
            transform: `scale(${interpolate(logoIn, [0, 1], [0.9, 1])})`,
            opacity: logoIn,
          }}
        >
          <div
            style={{
              width: 170,
              height: 170,
              borderRadius: 40,
              background: '#ffffff',
              border: `2px solid ${theme.border}`,
              boxShadow: '0 24px 80px rgba(0,0,0,0.12)',
              overflow: 'hidden',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 170, height: 170 }} />
          </div>
          <div style={{ fontSize: 140, color: theme.text, letterSpacing: -3 }}>
            <Wordmark />
          </div>
        </div>
        <div style={{ marginTop: 64, display: 'flex', flexDirection: 'column', gap: 18 }}>
          {LINES.map((line, i) => {
            const p = spring({
              frame: frame - 16 - i * 8,
              fps,
              config: { damping: 15, stiffness: 130 },
              durationInFrames: 20,
            });
            return (
              <div
                key={line}
                style={{
                  fontSize: 68,
                  fontWeight: i === 1 ? 700 : 600,
                  color: i === 1 ? theme.text : theme.textSecondary,
                  transform: `translateY(${interpolate(p, [0, 1], [60, 0])}px)`,
                  opacity: Math.min(p * 1.4, 1),
                }}
              >
                {line}
              </div>
            );
          })}
        </div>
        <div
          style={{
            marginTop: 84,
            display: 'flex',
            alignItems: 'center',
            gap: 28,
            opacity: byFade,
          }}
        >
          <span style={{ fontSize: 52, color: theme.text, letterSpacing: -1 }}>
            <Wordmark />
          </span>
          <span style={{ fontSize: 44, fontWeight: 500, color: theme.accent }}>·&nbsp;&nbsp;by</span>
          <Img src={staticFile('soundsafe-logo.png')} style={{ height: 92 }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
