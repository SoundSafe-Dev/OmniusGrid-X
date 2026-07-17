import React from 'react';
import { AbsoluteFill, Img, staticFile } from 'remotion';
import { theme } from '../theme';
import { Wordmark } from '../components/Wordmark';

/**
 * IG/LinkedIn carousel — "Can we take the rush order?" (6 square slides,
 * dark + light). An ORIGINAL growth-positive story told through panels
 * composed in the product's design language — no demo footage.
 */

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

type Pal = {
  isLight: boolean;
  bg: string;
  grid: string;
  gridOpacity: number;
  text: string;
  body: string;
  textSecondary: string;
  border: string;
  accentText: string;
  accentBorder: string;
  accentBg: string;
  green: string;
  greenBorder: string;
  greenBg: string;
  panelBg: string;
  panelBorder: string;
  panelHeaderBg: string;
  panelShadow: string;
  dot: string;
  bubbleBg: string;
  bubbleText: string;
  tileBorder: string;
  pillBorder: string;
};

const DARK: Pal = {
  isLight: false,
  bg: theme.darkBg,
  grid: theme.darkBorder,
  gridOpacity: 0.22,
  text: theme.darkText,
  body: 'rgba(250,250,250,0.88)',
  textSecondary: theme.darkTextSecondary,
  border: theme.darkBorder,
  accentText: theme.highlightSoft,
  accentBorder: 'rgba(59,130,246,0.45)',
  accentBg: 'rgba(59,130,246,0.10)',
  green: '#4ade80',
  greenBorder: 'rgba(74,222,128,0.5)',
  greenBg: 'rgba(74,222,128,0.08)',
  panelBg: 'linear-gradient(180deg, #15151b 0%, #0d0d11 100%)',
  panelBorder: 'rgba(255,255,255,0.12)',
  panelHeaderBg: 'rgba(255,255,255,0.03)',
  panelShadow: '0 0 120px rgba(59,130,246,0.12), 0 50px 140px rgba(0,0,0,0.55)',
  dot: 'rgba(255,255,255,0.2)',
  bubbleBg: '#ffffff',
  bubbleText: theme.darkBg,
  tileBorder: 'transparent',
  pillBorder: 'transparent',
};

const LIGHT: Pal = {
  isLight: true,
  bg: '#f7f7f8',
  grid: '#e6e6ea',
  gridOpacity: 0.6,
  text: '#141414',
  body: 'rgba(20,20,20,0.85)',
  textSecondary: '#5c5c62',
  border: '#e2e2e6',
  accentText: '#2563eb',
  accentBorder: 'rgba(37,99,235,0.35)',
  accentBg: 'rgba(59,130,246,0.08)',
  green: '#16a34a',
  greenBorder: 'rgba(22,163,74,0.45)',
  greenBg: 'rgba(22,163,74,0.07)',
  panelBg: '#ffffff',
  panelBorder: '#e2e2e6',
  panelHeaderBg: '#f3f3f5',
  panelShadow: '0 40px 110px rgba(15,23,42,0.16)',
  dot: '#c9c9cf',
  bubbleBg: '#171717',
  bubbleText: '#ffffff',
  tileBorder: '#e2e2e6',
  pillBorder: '#e2e2e6',
};

const PalCtx = React.createContext<Pal>(DARK);
const light = (C: React.FC): React.FC => {
  const L: React.FC = () => (
    <PalCtx.Provider value={LIGHT}>
      <C />
    </PalCtx.Provider>
  );
  return L;
};

const Slide: React.FC<{ step: number; children: React.ReactNode }> = ({ step, children }) => {
  const pal = React.useContext(PalCtx);
  return (
    <AbsoluteFill style={{ background: pal.bg, fontFamily: theme.fontFamily }}>
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${pal.grid} 1px, transparent 1px), linear-gradient(90deg, ${pal.grid} 1px, transparent 1px)`,
          backgroundSize: '120px 120px',
          opacity: pal.gridOpacity,
          maskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '130px 150px',
          display: 'flex',
          flexDirection: 'column',
          zIndex: 1,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 28 }}>
            <div
              style={{
                width: 92,
                height: 92,
                borderRadius: 22,
                background: '#ffffff',
                border: `3px solid ${pal.tileBorder}`,
                overflow: 'hidden',
                flexShrink: 0,
              }}
            >
              <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 92, height: 92 }} />
            </div>
            <span style={{ fontSize: 76, color: pal.text, letterSpacing: -1.5 }}>
              <Wordmark />
            </span>
          </div>
          <div style={{ display: 'flex', gap: 16 }}>
            {[1, 2, 3, 4, 5, 6].map((d) => (
              <div
                key={d}
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 11,
                  background: d === step ? theme.highlight : pal.border,
                }}
              />
            ))}
          </div>
        </div>
        {children}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 44, fontWeight: 600, color: pal.textSecondary }}>
            {step < 6 ? 'swipe →' : ''}
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
            <span style={{ fontSize: 28, fontWeight: 500, color: pal.textSecondary }}>by</span>
            <div
              style={{
                background: '#ffffff',
                borderRadius: 999,
                padding: '12px 28px',
                border: `3px solid ${pal.pillBorder}`,
                display: 'flex',
                alignItems: 'center',
              }}
            >
              <Img src={staticFile('soundsafe-logo.png')} style={{ height: 56 }} />
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const StepChip: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const pal = React.useContext(PalCtx);
  return (
    <div
      style={{
        alignSelf: 'flex-start',
        padding: '16px 42px',
        borderRadius: 999,
        border: `3px solid ${pal.accentBorder}`,
        background: pal.accentBg,
        color: pal.accentText,
        fontSize: 42,
        fontWeight: 800,
        letterSpacing: 6,
        textTransform: 'uppercase',
      }}
    >
      {children}
    </div>
  );
};

const Cap: React.FC<{ children: React.ReactNode; size?: number }> = ({ children, size = 110 }) => {
  const pal = React.useContext(PalCtx);
  return (
    <div
      style={{
        fontSize: size,
        fontWeight: 800,
        color: pal.text,
        letterSpacing: -2.5,
        lineHeight: 1.12,
      }}
    >
      {children}
    </div>
  );
};

/** product-style panel (window chrome + composed content) */
const Panel: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => {
  const pal = React.useContext(PalCtx);
  return (
    <div
      style={{
        width: '100%',
        borderRadius: 32,
        border: `3px solid ${pal.panelBorder}`,
        background: pal.panelBg,
        boxShadow: pal.panelShadow,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          padding: '26px 40px',
          background: pal.panelHeaderBg,
          borderBottom: `3px solid ${pal.panelBorder}`,
        }}
      >
        {[0, 1, 2].map((i) => (
          <div key={i} style={{ width: 18, height: 18, borderRadius: 9, background: pal.dot }} />
        ))}
        <span style={{ marginLeft: 16, fontSize: 34, fontWeight: 600, color: pal.textSecondary }}>
          {title}
        </span>
      </div>
      <div style={{ padding: '54px 60px', display: 'flex', flexDirection: 'column', gap: 44 }}>
        {children}
      </div>
    </div>
  );
};

const SrcChip: React.FC<{ label: string; tone?: 'blue' | 'green' }> = ({ label, tone = 'blue' }) => {
  const pal = React.useContext(PalCtx);
  const t =
    tone === 'green'
      ? { border: pal.greenBorder, bg: pal.greenBg, color: pal.green }
      : { border: pal.accentBorder, bg: pal.accentBg, color: pal.accentText };
  return (
    <span
      style={{
        width: 210,
        textAlign: 'center',
        padding: '14px 0',
        borderRadius: 16,
        border: `3px solid ${t.border}`,
        background: t.bg,
        color: t.color,
        fontSize: 36,
        fontWeight: 800,
        letterSpacing: 3,
        flexShrink: 0,
      }}
    >
      {label}
    </span>
  );
};

const B: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span style={{ color: theme.highlight }}>{children}</span>
);

const StepSlide: React.FC<{
  step: number;
  chip: string;
  cap: React.ReactNode;
  children: React.ReactNode;
}> = ({ step, chip, cap, children }) => (
  <Slide step={step}>
    <div style={{ marginTop: 100, display: 'flex', flexDirection: 'column', gap: 52 }}>
      <StepChip>{chip}</StepChip>
      <Cap>{cap}</Cap>
    </div>
    <div style={{ flex: 1 }} />
    {children}
    <div style={{ flex: 1 }} />
  </Slide>
);

/** 1 — hook */
export const CarouselS1: React.FC = () => {
  const pal = React.useContext(PalCtx);
  return (
    <Slide step={1}>
      <div style={{ flex: 1 }} />
      <Cap size={160}>
        Sales just called.
        <br />
        Big rush order.
        <br />
        <B>Can we take it?</B>
      </Cap>
      <div
        style={{
          marginTop: 70,
          fontSize: 56,
          fontWeight: 500,
          lineHeight: 1.45,
          color: pal.textSecondary,
        }}
      >
        A six-slide yes — built from an order book, a PM log and three live lines.
      </div>
      <div style={{ flex: 1 }} />
    </Slide>
  );
};

/** 2 — ask */
export const CarouselS2: React.FC = () => {
  const pal = React.useContext(PalCtx);
  return (
    <StepSlide
      step={2}
      chip="01 · Ask"
      cap={
        <>
          Plain language,
          <br />
          <B>straight from sales.</B>
        </>
      }
    >
      <Panel title="Correlation AI — new session">
        <div
          style={{
            alignSelf: 'flex-end',
            maxWidth: '86%',
            background: pal.bubbleBg,
            color: pal.bubbleText,
            borderRadius: '30px 30px 8px 30px',
            padding: '34px 50px',
            fontSize: 54,
            fontWeight: 600,
            lineHeight: 1.35,
          }}
        >
          Can we take the 12,000-unit rush order and still ship Friday?
        </div>
      </Panel>
    </StepSlide>
  );
};

/** 3 — the evidence */
export const CarouselS3: React.FC = () => {
  const pal = React.useContext(PalCtx);
  return (
    <StepSlide
      step={3}
      chip="02 · The evidence"
      cap={
        <>
          An order book, a PM log,
          <br />
          <B>three live lines.</B>
        </>
      }
    >
      <Panel title="Context — 3 sources correlated">
        {(
          [
            ['XLSX', 'blue', 'order-book_aug.xlsx', 'Sales'],
            ['PDF', 'blue', 'pm-schedule_q3.pdf', 'Maintenance'],
            ['● LIVE', 'green', 'Lines 1–3 — load & health', 'Machines'],
          ] as [string, 'blue' | 'green', string, string][]
        ).map(([tag, tone, file, dept]) => (
          <div key={file} style={{ display: 'flex', alignItems: 'center', gap: 40 }}>
            <SrcChip label={tag} tone={tone} />
            <span style={{ fontFamily: MONO, fontSize: 46, fontWeight: 700, color: pal.text }}>
              {file}
            </span>
            <span style={{ marginLeft: 'auto', fontSize: 40, color: pal.textSecondary }}>
              {dept}
            </span>
          </div>
        ))}
      </Panel>
    </StepSlide>
  );
};

/** 4 — the reasoning */
export const CarouselS4: React.FC = () => {
  const pal = React.useContext(PalCtx);
  return (
    <StepSlide
      step={4}
      chip="03 · The reasoning"
      cap={
        <>
          Three sources,
          <br />
          <B>one green light.</B>
        </>
      }
    >
      <Panel title="Correlation AI — cross-source reasoning">
        {(
          [
            ['1', <>The order book slots the run at <b>3,000 units/day</b> — squarely in Line 2's sweet spot.</>],
            ['2', <>The PM log shows Line 2 <b>serviced last Tuesday</b> — no maintenance windows in the way.</>],
            ['3', <>Live load has Line 2 cruising at <b>58% with clean vibration</b> — a full extra run fits without overtime.</>],
          ] as [string, React.ReactNode][]
        ).map(([n, line]) => (
          <div key={n} style={{ display: 'flex', gap: 36, alignItems: 'flex-start' }}>
            <div
              style={{
                width: 64,
                height: 64,
                borderRadius: 32,
                border: `3px solid ${pal.accentBorder}`,
                background: pal.accentBg,
                color: pal.accentText,
                fontSize: 36,
                fontWeight: 800,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              {n}
            </div>
            <div style={{ fontSize: 46, lineHeight: 1.4, color: pal.body }}>{line}</div>
          </div>
        ))}
      </Panel>
    </StepSlide>
  );
};

/** 5 — the verdict */
export const CarouselS5: React.FC = () => {
  const pal = React.useContext(PalCtx);
  return (
    <StepSlide
      step={5}
      chip="04 · The verdict"
      cap={
        <>
          The answer: yes —
          <br />
          <B>shipped Friday.</B>
        </>
      }
    >
      <Panel title="Answer — scored, actions attached">
        <div style={{ display: 'flex', gap: 36, alignItems: 'flex-start' }}>
          <span
            style={{
              fontSize: 42,
              fontWeight: 800,
              color: pal.green,
              border: `3px solid ${pal.greenBorder}`,
              background: pal.greenBg,
              borderRadius: 14,
              padding: '12px 28px',
              whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
          >
            GO · 96
          </span>
          <div style={{ fontSize: 48, lineHeight: 1.4, color: pal.body }}>
            <b>Take the order — Line 2 covers it.</b> Materials on hand, PM already
            done, margin intact. Capacity you owned all along, found in nine seconds.
          </div>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
          <span
            style={{
              fontSize: 40,
              fontWeight: 700,
              color: pal.isLight ? '#ffffff' : '#0a0a0a',
              background: pal.isLight ? '#2563eb' : theme.highlightSoft,
              borderRadius: 999,
              padding: '18px 40px',
            }}
          >
            Confirm the order — reply to Sales
          </span>
          <span
            style={{
              fontSize: 40,
              fontWeight: 600,
              color: pal.body,
              border: `3px solid ${pal.border}`,
              borderRadius: 999,
              padding: '18px 40px',
            }}
          >
            Kanban → Production <span style={{ color: pal.green }}>✓ scheduled</span>
          </span>
        </div>
      </Panel>
    </StepSlide>
  );
};

/** 6 — CTA */
export const CarouselS6: React.FC = () => {
  const pal = React.useContext(PalCtx);
  return (
    <Slide step={6}>
      <div style={{ flex: 1 }} />
      <Cap size={150}>
        Growth hides
        <br />
        in your data too.
        <br />
        <B>Go find it.</B>
      </Cap>
      <div
        style={{
          marginTop: 70,
          fontSize: 56,
          fontWeight: 700,
          color: pal.textSecondary,
        }}
      >
        OmniusGrid — the correlation engine for Industry 4.0.
      </div>
      <div style={{ flex: 1 }} />
    </Slide>
  );
};

export const CarouselS1Light = light(CarouselS1);
export const CarouselS2Light = light(CarouselS2);
export const CarouselS3Light = light(CarouselS3);
export const CarouselS4Light = light(CarouselS4);
export const CarouselS5Light = light(CarouselS5);
export const CarouselS6Light = light(CarouselS6);
