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
import Dashboard from '../../../src/pages/Dashboard';
import OEE from '../../../src/pages/OEE';
import Assets from '../../../src/pages/Assets';
import Kanban from '../../../src/pages/Kanban';
import ERPIntegrationsPage from '../../../src/pages/erp/ERPIntegrations';
import { TransportationManagement } from '../../../src/pages/logistics/TransportationManagement';
import { YardManagement } from '../../../src/pages/logistics';
import { CorrelationAIPane } from '../../../src/components/nlp/CorrelationAIPane';
import { theme } from '../theme';
import { MOBILE_W, MOBILE_H } from './theme';
import { MiniStage } from '../components/MiniStage';
import { Wordmark } from '../components/Wordmark';

/**
 * Portrait finale: the 8 live panes fly into a 2x4 grid, then converge into
 * one stack behind the logo — same beats and timing as the desktop edition.
 */

const CARD_W = 980;
const CARD_H = 551;

const CARDS: {
  route: string;
  page: React.ReactNode;
  fitHeight?: boolean;
  extraCss?: string;
}[] = [
  { route: '/nlp', page: <CorrelationAIPane />, fitHeight: true },
  { route: '/', page: <Dashboard /> },
  { route: '/oee', page: <OEE /> },
  { route: '/kanban', page: <Kanban /> },
  { route: '/assets', page: <Assets /> },
  { route: '/logistics/transportation', page: <TransportationManagement /> },
  { route: '/logistics/yard', page: <YardManagement /> },
  { route: '/erp', page: <ERPIntegrationsPage /> },
];

const GRID_X = [62, 1118];
const GRID_Y = [560, 1195, 1830, 2465];
const CONVERGE_AT = 140;

export const MobileStackScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const titleIn = spring({
    frame: frame - 14,
    fps,
    config: { damping: 15, stiffness: 120 },
    durationInFrames: 20,
  });
  const titleOut = interpolate(frame, [CONVERGE_AT + 8, CONVERGE_AT + 28], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const logoIn = spring({
    frame: frame - (CONVERGE_AT + 38),
    fps,
    config: { damping: 13, stiffness: 110 },
    durationInFrames: 22,
  });

  return (
    <AbsoluteFill style={{ background: theme.darkBg, fontFamily: theme.fontFamily }}>
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${theme.darkBorder} 1px, transparent 1px), linear-gradient(90deg, ${theme.darkBorder} 1px, transparent 1px)`,
          backgroundSize: '120px 120px',
          opacity: 0.2,
          maskImage: 'radial-gradient(ellipse at center, black 25%, transparent 80%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, black 25%, transparent 80%)',
        }}
      />
      {/* grid-phase headline */}
      <div
        style={{
          position: 'absolute',
          top: 200,
          left: 60,
          right: 60,
          textAlign: 'center',
          fontSize: 92,
          fontWeight: 800,
          color: theme.darkText,
          letterSpacing: -1.5,
          lineHeight: 1.12,
          opacity: Math.min(titleIn * 1.3, 1) * titleOut,
          transform: `translateY(${interpolate(titleIn, [0, 1], [40, 0])}px)`,
          zIndex: 5,
        }}
      >
        Every department's data, one platform.
      </div>
      {/* the panes */}
      <div style={{ position: 'absolute', inset: 0, transformStyle: 'preserve-3d' }}>
        {CARDS.map((card, i) => {
          const col = i % 2;
          const row = Math.floor(i / 2);
          const gx = GRID_X[col];
          const gy = GRID_Y[row];

          const flyIn = spring({
            frame: frame - 4 - i * 5,
            fps,
            config: { damping: 16, stiffness: 100 },
            durationInFrames: 26,
          });
          const converge = spring({
            frame: frame - CONVERGE_AT - (7 - i) * 2,
            fps,
            config: { damping: 18, stiffness: 80 },
            durationInFrames: 45,
          });

          const gridY = gy + interpolate(flyIn, [0, 1], [620, 0]);
          const gridRotY = col === 0 ? 5 : -5;
          // collapse target: the logo tile's center — the panes shrink into
          // it and fade out completely as the identity pops in
          const cx = MOBILE_W / 2 - CARD_W / 2 + (i - 3.5) * 6;
          const cy = 2015 - CARD_H / 2 + (i - 3.5) * 5;

          const x = interpolate(converge, [0, 1], [gx, cx]);
          const y = interpolate(converge, [0, 1], [gridY, cy]);
          const sc = interpolate(converge, [0, 1], [1, 0.18]);
          const rotY = interpolate(converge, [0, 1], [gridRotY, 0]);
          const rotZ = interpolate(converge, [0, 1], [0, (i - 3.5) * 2.2]);
          const opacity =
            Math.min(flyIn * 1.3, 1) *
            interpolate(converge, [0.55, 0.92], [1, 0], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });

          return (
            <div
              key={card.route}
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                width: CARD_W,
                height: CARD_H,
                borderRadius: 20,
                overflow: 'hidden',
                border: `2px solid ${theme.darkBorder}`,
                boxShadow: '0 40px 120px rgba(0,0,0,0.7)',
                transform: `translate(${x}px, ${y}px) perspective(3600px) rotateX(${interpolate(converge, [0, 1], [5, 0])}deg) rotateY(${rotY}deg) rotateZ(${rotZ}deg) scale(${sc})`,
                transformOrigin: 'center center',
                opacity,
                zIndex: 10 - i,
              }}
            >
              <MiniStage
                route={card.route}
                width={CARD_W}
                fitHeight={card.fitHeight}
                extraCss={card.extraCss}
              >
                {card.page}
              </MiniStage>
            </div>
          );
        })}
      </div>
      {/* converged identity */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 1900,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 34,
          opacity: Math.min(logoIn * 1.3, 1),
          transform: `translateY(${interpolate(logoIn, [0, 1], [70, 0])}px)`,
          zIndex: 20,
        }}
      >
        <div
          style={{
            width: 230,
            height: 230,
            borderRadius: 52,
            background: '#ffffff',
            boxShadow: '0 0 120px rgba(250,250,250,0.25), 0 40px 120px rgba(0,0,0,0.6)',
            overflow: 'hidden',
          }}
        >
          <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 230, height: 230 }} />
        </div>
        <div style={{ fontSize: 124, color: theme.darkText, letterSpacing: -2.5 }}>
          <Wordmark />
        </div>
        <div
          style={{
            fontSize: 54,
            fontWeight: 600,
            color: theme.darkTextSecondary,
            textAlign: 'center',
            padding: '0 120px',
            lineHeight: 1.3,
          }}
        >
          The correlation engine for your entire operation.
        </div>
      </div>
    </AbsoluteFill>
  );
};
