import React from 'react';
import { AbsoluteFill, Img, staticFile } from 'remotion';
import { theme } from '../theme';
import { Wordmark } from '../components/Wordmark';

/**
 * Prologue announcement cards — the minimal piece that precedes the
 * campaign: overline, logo lockup, founder quote, SoundSafe credit.
 * Dark + light editions; 4:5 (2160x2700) and 9:16 (2160x3840).
 */

const QUOTE = (
  <>
    Every operation already has its answers — scattered across systems
    that don't talk. We built OmniusGrid to turn them into{' '}
    <span style={{ whiteSpace: 'nowrap' }}>one conversation.</span>
  </>
);
const ATTRIB_NAME = 'Hamad Dada';
const ATTRIB_ROLE = 'SoundSafe.ai';

type Pal = {
  bg: string;
  grid: string;
  text: string;
  secondary: string;
  tileBg: string;
  tileBorder: string;
  pillBorder: string;
  pillBg: string;
};

const DARK: Pal = {
  bg: '#0a0a0a',
  grid: '#1b1b1f',
  text: '#fafafa',
  secondary: '#a3a3a3',
  tileBg: '#ffffff',
  tileBorder: 'transparent',
  pillBorder: 'rgba(255,255,255,0.16)',
  pillBg: 'rgba(255,255,255,0.04)',
};

const LIGHT: Pal = {
  bg: '#f7f7f8',
  grid: '#e6e6ea',
  text: '#141414',
  secondary: '#5c5c62',
  tileBg: '#ffffff',
  tileBorder: '#e2e2e6',
  pillBorder: 'rgba(20,20,20,0.16)',
  pillBg: 'rgba(20,20,20,0.03)',
};

const Card: React.FC<{ pal: Pal; tall?: boolean }> = ({ pal, tall }) => (
  <AbsoluteFill style={{ background: pal.bg, fontFamily: theme.fontFamily }}>
    <AbsoluteFill
      style={{
        backgroundImage: `linear-gradient(${pal.grid} 1px, transparent 1px), linear-gradient(90deg, ${pal.grid} 1px, transparent 1px)`,
        backgroundSize: '120px 120px',
        opacity: 0.55,
        maskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
        WebkitMaskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
      }}
    />
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: tall ? '340px 200px' : '220px 200px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        gap: tall ? 110 : 90,
        zIndex: 1,
      }}
    >
      <span
        style={{
          fontSize: 40,
          fontWeight: 700,
          letterSpacing: 10,
          color: pal.secondary,
          border: `3px solid ${pal.pillBorder}`,
          background: pal.pillBg,
          borderRadius: 999,
          padding: '18px 48px',
        }}
      >
        INTRODUCING
      </span>

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 56 }}>
        <div
          style={{
            width: 260,
            height: 260,
            borderRadius: 58,
            background: pal.tileBg,
            border: `3px solid ${pal.tileBorder}`,
            overflow: 'hidden',
            boxShadow:
              pal === DARK
                ? '0 0 160px rgba(250,250,250,0.2)'
                : '0 24px 70px rgba(15,23,42,0.07)',
          }}
        >
          <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 260, height: 260 }} />
        </div>
        <div style={{ fontSize: 140, color: pal.text, letterSpacing: -3, lineHeight: 1 }}>
          <Wordmark />
        </div>
        <div style={{ height: 8, width: 380, borderRadius: 4, background: theme.highlight }} />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 54 }}>
        <div
          style={{
            fontSize: tall ? 66 : 62,
            fontWeight: 500,
            lineHeight: 1.48,
            color: pal.text,
            maxWidth: 1560,
          }}
        >
          <span style={{ color: theme.highlight, fontWeight: 800 }}>&ldquo;</span>
          {QUOTE}
          <span style={{ color: theme.highlight, fontWeight: 800 }}>&rdquo;</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <span style={{ fontSize: 46, fontWeight: 700, color: pal.text }}>{ATTRIB_NAME}</span>
          <span style={{ fontSize: 36, fontWeight: 500, color: pal.secondary }}>{ATTRIB_ROLE}</span>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <span style={{ fontSize: 36, fontWeight: 500, color: pal.secondary }}>by</span>
        <div
          style={{
            background: '#ffffff',
            borderRadius: 999,
            border: pal === LIGHT ? '3px solid #e2e2e6' : 'none',
            padding: '16px 36px',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <Img src={staticFile('soundsafe-logo.png')} style={{ height: 66 }} />
        </div>
      </div>
    </div>
  </AbsoluteFill>
);

export const PrologueDark45: React.FC = () => <Card pal={DARK} />;
export const PrologueLight45: React.FC = () => <Card pal={LIGHT} />;
export const PrologueDarkStory: React.FC = () => <Card pal={DARK} tall />;
export const PrologueLightStory: React.FC = () => <Card pal={LIGHT} tall />;
