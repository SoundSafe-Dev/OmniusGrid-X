import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { theme } from '../theme';
import { MOBILE_W, MOBILE_H } from './theme';
import { MiniPortraitStage } from './components/MiniPortraitStage';
import { PanZoomMove } from '../components/PanZoom';

/**
 * Portrait "important page" presentation, v2: large phone-readable type on
 * top, then a full-bleed TALL portrait window onto the live desktop page
 * (MiniPortraitStage) — camera moves in page coordinates. The correlation
 * chip sits between the copy and the window.
 */
interface MobileFramedSceneProps {
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
  /** Window height — match the page: tall pages fill 1900; a standard
   *  1036-tall page should pass ~1290 so the window has no internal gaps */
  frameH?: number;
  /** Window top — defaults to bottom-anchored with a 120px margin */
  frameTop?: number;
}

export const FRAME_W = 2128;
const FRAME_X = (MOBILE_W - FRAME_W) / 2;

export const MobileFramedScene: React.FC<MobileFramedSceneProps> = ({
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
  frameH = 1900,
  frameTop,
}) => {
  const frameY = frameTop ?? MOBILE_H - frameH - 120;
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
    frame: frame - 30 - bullets.length * 6,
    fps,
    config: { damping: 14, stiffness: 130 },
    durationInFrames: 18,
  });
  const chipPulse = 1 + 0.02 * Math.sin((frame / fps) * Math.PI * 1.6);

  return (
    <AbsoluteFill style={{ background: theme.darkBg, fontFamily: theme.fontFamily }}>
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${theme.darkBorder} 1px, transparent 1px), linear-gradient(90deg, ${theme.darkBorder} 1px, transparent 1px)`,
          backgroundSize: '120px 120px',
          opacity: 0.24,
          maskImage: 'radial-gradient(ellipse at 40% 25%, black 20%, transparent 78%)',
          WebkitMaskImage: 'radial-gradient(ellipse at 40% 25%, black 20%, transparent 78%)',
        }}
      />
      {/* explanation block on top — phone-readable sizes */}
      <div
        style={{
          position: 'absolute',
          left: 100,
          right: 100,
          top: 250,
          display: 'flex',
          flexDirection: 'column',
          gap: 56,
          opacity: Math.min(titleIn * 1.3, 1),
          transform: `translateY(${interpolate(titleIn, [0, 1], [50, 0])}px)`,
        }}
      >
        <div
          style={{
            alignSelf: 'flex-start',
            padding: '16px 42px',
            borderRadius: 999,
            border: `2px solid ${theme.darkBorder}`,
            color: theme.darkTextSecondary,
            fontSize: 42,
            fontWeight: 700,
            letterSpacing: 6,
            textTransform: 'uppercase',
          }}
        >
          {overline}
        </div>
        <div
          style={{
            fontSize: 176,
            fontWeight: 800,
            color: theme.darkText,
            letterSpacing: -3,
            lineHeight: 1.04,
          }}
        >
          {title}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 42, marginTop: 4 }}>
          {bullets.map((b, i) => {
            const p = spring({
              frame: frame - 24 - i * 7,
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
                  gap: 30,
                  opacity: Math.min(p * 1.4, 1),
                  transform: `translateX(${interpolate(p, [0, 1], [-40, 0])}px)`,
                }}
              >
                <div
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 11,
                    background: theme.highlight,
                    marginTop: 30,
                    flexShrink: 0,
                    boxShadow: '0 0 20px rgba(59,130,246,0.6)',
                  }}
                />
                <div
                  style={{
                    fontSize: 76,
                    fontWeight: 500,
                    color: 'rgba(250,250,250,0.9)',
                    lineHeight: 1.28,
                  }}
                >
                  {b}
                </div>
              </div>
            );
          })}
        </div>
        <div
          style={{
            alignSelf: 'flex-start',
            marginTop: 2,
            padding: '26px 52px',
            borderRadius: 24,
            border: `2px solid rgba(59,130,246,0.55)`,
            background: 'rgba(59,130,246,0.10)',
            color: theme.highlightSoft,
            fontSize: 58,
            fontWeight: 700,
            opacity: Math.min(chipIn * 1.4, 1),
            transform: `scale(${interpolate(chipIn, [0, 1], [0.9, 1]) * chipPulse})`,
            transformOrigin: 'left center',
          }}
        >
          {chipText}
        </div>
      </div>
      {/* full-bleed tall portrait window onto the live page */}
      <div
        style={{
          position: 'absolute',
          left: FRAME_X,
          top: frameY,
          width: FRAME_W,
          height: frameH,
          borderRadius: 26,
          overflow: 'hidden',
          border: `2px solid ${theme.darkBorder}`,
          boxShadow: '0 60px 180px rgba(0,0,0,0.75)',
          opacity: Math.min(frameIn * 1.2, 1),
          transform: `perspective(4000px) translateY(${interpolate(frameIn, [0, 1], [140, 0])}px) rotateX(${interpolate(frameIn, [0, 1], [5, 1.5])}deg)`,
        }}
      >
        <MiniPortraitStage
          route={route}
          width={FRAME_W}
          height={frameH}
          moves={moves}
          overlays={overlays}
          stageOverlay={stageOverlay}
          extraCss={extraCss}
          fitHeight={fitHeight}
        >
          {page}
        </MiniPortraitStage>
      </div>
    </AbsoluteFill>
  );
};
