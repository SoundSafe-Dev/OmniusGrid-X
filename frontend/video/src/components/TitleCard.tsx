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

/** Subtle animated grid texture on the light brand background */
const GridBackdrop: React.FC = () => {
  const frame = useCurrentFrame();
  const drift = interpolate(frame, [0, 120], [0, 40]);
  return (
    <AbsoluteFill
      style={{
        backgroundImage: `linear-gradient(${theme.border} 1px, transparent 1px), linear-gradient(90deg, ${theme.border} 1px, transparent 1px)`,
        backgroundSize: '96px 96px',
        backgroundPosition: `${drift}px ${drift * 0.5}px`,
        opacity: 0.55,
        maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
        WebkitMaskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
      }}
    />
  );
};

export const KineticWords: React.FC<{
  words: string[];
  fontSize: number;
  fontWeight: number;
  color: string;
  startAt: number;
  stagger?: number;
  letterSpacing?: number;
}> = ({ words, fontSize, fontWeight, color, startAt, stagger = 4, letterSpacing = -1 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center' }}>
      {words.map((word, i) => {
        const p = spring({
          frame: frame - startAt - i * stagger,
          fps,
          config: { damping: 14, stiffness: 130 },
          durationInFrames: 20,
        });
        return (
          <span
            key={i}
            style={{
              overflow: 'hidden',
              display: 'inline-block',
              // explicit word gap — flex `gap` collapsed in headless renders
              marginRight: i < words.length - 1 ? '0.34em' : 0,
              fontSize,
            }}
          >
            <span
              style={{
                display: 'inline-block',
                transform: `translateY(${interpolate(p, [0, 1], [110, 0])}%)`,
                opacity: Math.min(p * 1.5, 1),
                fontSize,
                fontWeight,
                color,
                letterSpacing,
                lineHeight: 1.18,
              }}
            >
              {word}
            </span>
          </span>
        );
      })}
    </div>
  );
};

export const TitleCard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const logoIn = spring({
    frame: frame - 2,
    fps,
    config: { damping: 13, stiffness: 110 },
    durationInFrames: 22,
  });
  const nameIn = spring({
    frame: frame - 8,
    fps,
    config: { damping: 14, stiffness: 130 },
    durationInFrames: 20,
  });
  const underline = spring({
    frame: frame - 30,
    fps,
    config: { damping: 18, stiffness: 90 },
    durationInFrames: 26,
  });
  const byFade = interpolate(frame, [44, 62], [0, 1], {
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
      <GridBackdrop />
      <div
        style={{
          textAlign: 'center',
          padding: '0 240px',
          zIndex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
        }}
      >
        <div
          style={{
            width: 300,
            height: 300,
            borderRadius: 64,
            background: '#ffffff',
            border: `2px solid ${theme.border}`,
            boxShadow: '0 40px 120px rgba(0,0,0,0.14)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transform: `scale(${interpolate(logoIn, [0, 1], [0.7, 1])})`,
            opacity: logoIn,
            marginBottom: 56,
            overflow: 'hidden',
          }}
        >
          <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 300, height: 300 }} />
        </div>
        <div style={{ overflow: 'hidden', display: 'inline-block' }}>
          <div
            style={{
              display: 'inline-block',
              transform: `translateY(${interpolate(nameIn, [0, 1], [110, 0])}%)`,
              opacity: Math.min(nameIn * 1.5, 1),
              fontSize: 190,
              color: theme.text,
              letterSpacing: -3,
              lineHeight: 1.18,
            }}
          >
            <Wordmark />
          </div>
        </div>
        <div
          style={{
            height: 10,
            width: 560,
            margin: '38px auto 54px',
            borderRadius: 5,
            background: theme.text,
            transform: `scaleX(${underline})`,
            transformOrigin: 'center',
          }}
        />
        <KineticWords
          words={'Unleash the power of data correlation'.split(' ')}
          fontSize={86}
          fontWeight={600}
          color={theme.textSecondary}
          startAt={20}
          letterSpacing={-0.5}
        />
        <div
          style={{
            marginTop: 72,
            display: 'flex',
            alignItems: 'center',
            gap: 26,
            opacity: byFade,
          }}
        >
          <span style={{ fontSize: 42, fontWeight: 500, color: theme.accent }}>by</span>
          <Img src={staticFile('soundsafe-logo.png')} style={{ height: 96 }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
