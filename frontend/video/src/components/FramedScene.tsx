import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { theme } from '../theme';
import { MiniStage } from './MiniStage';
import { PanZoomMove } from './PanZoom';

/**
 * "Important page" presentation: charcoal backdrop, explanation panel on the
 * left (overline, title, feature bullets, correlation-AI chip), the live page
 * in a rounded frame on the right. The page starts fully visible in the
 * frame, then its internal camera punches into features.
 */
interface FramedSceneProps {
  overline: string;
  title: string;
  bullets: string[];
  route: string;
  page: React.ReactNode;
  moves?: PanZoomMove[];
  overlays?: React.ReactNode;
  stageOverlay?: React.ReactNode;
  extraCss?: string;
  fitHeight?: boolean;
  chipText?: string;
}

const FRAME_W = 2400;
const FRAME_X = 1200;

export const FramedScene: React.FC<FramedSceneProps> = ({
  overline,
  title,
  bullets,
  route,
  page,
  moves,
  overlays,
  stageOverlay,
  extraCss,
  fitHeight,
  chipText = '⚡ Streams into the Correlation AI',
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const frameIn = spring({
    frame: frame - 4,
    fps,
    config: { damping: 16, stiffness: 110 },
    durationInFrames: 22,
  });
  const titleIn = spring({
    frame: frame - 8,
    fps,
    config: { damping: 15, stiffness: 120 },
    durationInFrames: 20,
  });
  const chipIn = spring({
    frame: frame - 34 - bullets.length * 6,
    fps,
    config: { damping: 14, stiffness: 130 },
    durationInFrames: 18,
  });
  const chipPulse = 1 + 0.02 * Math.sin((frame / fps) * Math.PI * 1.6);

  const frameH = (FRAME_W * 1080) / 1920;

  return (
    <AbsoluteFill style={{ background: theme.darkBg, fontFamily: theme.fontFamily }}>
      {/* subtle monochrome grid texture */}
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${theme.darkBorder} 1px, transparent 1px), linear-gradient(90deg, ${theme.darkBorder} 1px, transparent 1px)`,
          backgroundSize: '120px 120px',
          opacity: 0.24,
          maskImage: 'radial-gradient(ellipse at 30% 40%, black 20%, transparent 78%)',
          WebkitMaskImage: 'radial-gradient(ellipse at 30% 40%, black 20%, transparent 78%)',
        }}
      />
      {/* left explanation panel */}
      <div
        style={{
          position: 'absolute',
          left: 170,
          top: 0,
          bottom: 0,
          width: 900,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 44,
          opacity: Math.min(titleIn * 1.3, 1),
          transform: `translateY(${interpolate(titleIn, [0, 1], [50, 0])}px)`,
        }}
      >
        <div
          style={{
            alignSelf: 'flex-start',
            padding: '14px 34px',
            borderRadius: 999,
            border: `2px solid ${theme.darkBorder}`,
            color: theme.darkTextSecondary,
            fontSize: 32,
            fontWeight: 700,
            letterSpacing: 5,
            textTransform: 'uppercase',
          }}
        >
          {overline}
        </div>
        <div style={{ fontSize: 108, fontWeight: 800, color: theme.darkText, letterSpacing: -2, lineHeight: 1.06 }}>
          {title}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 30, marginTop: 8 }}>
          {bullets.map((b, i) => {
            const p = spring({
              frame: frame - 26 - i * 7,
              fps,
              config: { damping: 15, stiffness: 130 },
              durationInFrames: 18,
            });
            return (
              <div
                key={b}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 24,
                  opacity: Math.min(p * 1.4, 1),
                  transform: `translateX(${interpolate(p, [0, 1], [-40, 0])}px)`,
                }}
              >
                <div
                  style={{
                    width: 16,
                    height: 16,
                    borderRadius: 8,
                    background: theme.highlight,
                    marginTop: 20,
                    flexShrink: 0,
                    boxShadow: '0 0 18px rgba(59,130,246,0.6)',
                  }}
                />
                <div style={{ fontSize: 46, fontWeight: 500, color: 'rgba(250,250,250,0.88)', lineHeight: 1.32 }}>
                  {b}
                </div>
              </div>
            );
          })}
        </div>
        <div
          style={{
            alignSelf: 'flex-start',
            marginTop: 18,
            padding: '20px 40px',
            borderRadius: 20,
            border: `2px solid rgba(59,130,246,0.55)`,
            background: 'rgba(59,130,246,0.10)',
            color: theme.highlightSoft,
            fontSize: 38,
            fontWeight: 700,
            opacity: Math.min(chipIn * 1.4, 1),
            transform: `scale(${interpolate(chipIn, [0, 1], [0.9, 1]) * chipPulse})`,
            transformOrigin: 'left center',
          }}
        >
          {chipText}
        </div>
      </div>
      {/* framed live page */}
      <div
        style={{
          position: 'absolute',
          left: FRAME_X,
          top: (2160 - frameH) / 2,
          width: FRAME_W,
          height: frameH,
          borderRadius: 30,
          overflow: 'hidden',
          border: `2px solid ${theme.darkBorder}`,
          boxShadow: '0 60px 180px rgba(0,0,0,0.75)',
          opacity: Math.min(frameIn * 1.2, 1),
          transform: `perspective(4000px) translateX(${interpolate(frameIn, [0, 1], [160, 0])}px) rotateY(${interpolate(frameIn, [0, 1], [-7, -2.5])}deg)`,
        }}
      >
        <MiniStage
          route={route}
          width={FRAME_W}
          moves={moves}
          overlays={overlays}
          stageOverlay={stageOverlay}
          extraCss={extraCss}
          fitHeight={fitHeight}
        >
          {page}
        </MiniStage>
      </div>
    </AbsoluteFill>
  );
};
