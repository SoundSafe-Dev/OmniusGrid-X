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
import { MiniStage } from '../components/MiniStage';
import { Wordmark } from '../components/Wordmark';

/**
 * Finale: every live pane flies into a tilted grid, then the panes converge
 * and stack into one — OmniusGrid, the correlation engine. Monochrome
 * charcoal backdrop; all panes are real mounted pages, not screenshots.
 */

const CARD_W = 800;
const CARD_H = 450;

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

const GRID_X = [58, 1033, 2008, 2983];
const GRID_Y = [460, 1230];
const CONVERGE_AT = 140;

export const StackScene: React.FC = () => {
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
          top: 120,
          left: 0,
          right: 0,
          textAlign: 'center',
          fontSize: 96,
          fontWeight: 800,
          color: theme.darkText,
          letterSpacing: -1.5,
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
          const col = i % 4;
          const row = Math.floor(i / 4);
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

          // grid pose
          const gridY = gy + interpolate(flyIn, [0, 1], [620, 0]);
          const gridRotY = [7, 3, -3, -7][col];
          // stacked pose (center, fanned)
          const cx = (3840 - CARD_W * 0.42) / 2 + (i - 3.5) * 14;
          const cy = (2160 - CARD_H * 0.42) / 2 - 60 + (i - 3.5) * 12;

          const x = interpolate(converge, [0, 1], [gx, cx]);
          const y = interpolate(converge, [0, 1], [gridY, cy]);
          const sc = interpolate(converge, [0, 1], [1, 0.42]);
          const rotY = interpolate(converge, [0, 1], [gridRotY, 0]);
          const rotZ = interpolate(converge, [0, 1], [0, (i - 3.5) * 2.2]);
          const opacity =
            Math.min(flyIn * 1.3, 1) * interpolate(converge, [0.6, 1], [1, i === 0 ? 1 : 0.6], {
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
                transform: `translate(${x}px, ${y}px) perspective(3600px) rotateX(${interpolate(converge, [0, 1], [6, 0])}deg) rotateY(${rotY}deg) rotateZ(${rotZ}deg) scale(${sc})`,
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
          top: 1180,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 30,
          opacity: Math.min(logoIn * 1.3, 1),
          transform: `translateY(${interpolate(logoIn, [0, 1], [70, 0])}px)`,
          zIndex: 20,
        }}
      >
        <div
          style={{
            width: 210,
            height: 210,
            borderRadius: 48,
            background: '#ffffff',
            boxShadow: '0 0 120px rgba(250,250,250,0.25), 0 40px 120px rgba(0,0,0,0.6)',
            overflow: 'hidden',
          }}
        >
          <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 210, height: 210 }} />
        </div>
        <div style={{ fontSize: 120, color: theme.darkText, letterSpacing: -2.5 }}>
          <Wordmark />
        </div>
        <div style={{ fontSize: 58, fontWeight: 600, color: theme.darkTextSecondary }}>
          The correlation engine for your entire operation.
        </div>
      </div>
    </AbsoluteFill>
  );
};
