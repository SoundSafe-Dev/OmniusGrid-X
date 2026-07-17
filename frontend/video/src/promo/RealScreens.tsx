import React from 'react';
import { AbsoluteFill, Img, staticFile } from 'remotion';
import { theme } from '../theme';
import { Wordmark } from '../components/Wordmark';

/**
 * "Real screens" social cards — witty lines proven by ACTUAL product UI,
 * cropped from the live pages (frontend/public/shots, regenerated via the
 * Shot* stills in Root). Every card ships dark/light × square/story.
 */

type Pal = {
  isLight: boolean;
  bg: string;
  grid: string;
  gridOpacity: number;
  text: string;
  textSecondary: string;
  border: string;
  kicker: string;
  winBorder: string;
  winHeaderBg: string;
  winShadow: string;
  dot: string;
  tileBorder: string;
  pillBorder: string;
};

const DARK: Pal = {
  isLight: false,
  bg: theme.darkBg,
  grid: theme.darkBorder,
  gridOpacity: 0.22,
  text: theme.darkText,
  textSecondary: theme.darkTextSecondary,
  border: theme.darkBorder,
  kicker: theme.highlightSoft,
  winBorder: 'rgba(255,255,255,0.14)',
  winHeaderBg: '#17171b',
  winShadow: '0 0 120px rgba(59,130,246,0.12), 0 50px 140px rgba(0,0,0,0.55)',
  dot: 'rgba(255,255,255,0.2)',
  tileBorder: 'transparent',
  pillBorder: 'transparent',
};

const LIGHT: Pal = {
  isLight: true,
  bg: '#f7f7f8',
  grid: '#e6e6ea',
  gridOpacity: 0.6,
  text: '#141414',
  textSecondary: '#5c5c62',
  border: '#e2e2e6',
  kicker: '#2563eb',
  winBorder: '#d9d9de',
  winHeaderBg: '#ececef',
  winShadow: '0 40px 110px rgba(15,23,42,0.16)',
  dot: '#c9c9cf',
  tileBorder: '#e2e2e6',
  pillBorder: '#e2e2e6',
};

const PalCtx = React.createContext<Pal>(DARK);
const TallCtx = React.createContext(0);

const light = (C: React.FC): React.FC => {
  const L: React.FC = () => (
    <PalCtx.Provider value={LIGHT}>
      <C />
    </PalCtx.Provider>
  );
  return L;
};
const tallVariant = (C: React.FC, scale = 1.08): React.FC => {
  const T: React.FC = () => (
    <TallCtx.Provider value={scale}>
      <C />
    </TallCtx.Provider>
  );
  return T;
};

/** browser-style window framing a real UI crop */
const Window: React.FC<{ title: string; img: string; w: number }> = ({ title, img, w }) => {
  const pal = React.useContext(PalCtx);
  return (
    <div
      style={{
        width: w,
        borderRadius: 28,
        border: `3px solid ${pal.winBorder}`,
        boxShadow: pal.winShadow,
        overflow: 'hidden',
        background: '#ffffff',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          padding: '22px 34px',
          background: pal.winHeaderBg,
          borderBottom: `3px solid ${pal.winBorder}`,
        }}
      >
        {[0, 1, 2].map((i) => (
          <div key={i} style={{ width: 16, height: 16, borderRadius: 8, background: pal.dot }} />
        ))}
        <span
          style={{
            marginLeft: 14,
            fontSize: 30,
            fontWeight: 600,
            color: pal.isLight ? pal.textSecondary : 'rgba(250,250,250,0.6)',
          }}
        >
          {title}
        </span>
      </div>
      <Img src={staticFile(`shots/${img}.png`)} style={{ width: '100%', display: 'block' }} />
    </div>
  );
};

const RSCard: React.FC<{
  headline: React.ReactNode;
  kicker: React.ReactNode;
  winTitle: string;
  img: string;
  imgW: number;
}> = ({ headline, kicker, winTitle, img, imgW }) => {
  const pal = React.useContext(PalCtx);
  const tallScale = React.useContext(TallCtx);
  const tall = tallScale > 0;
  const logo = tall ? 126 : 92;
  return (
    <AbsoluteFill
      style={{
        background: pal.bg,
        fontFamily: theme.fontFamily,
      }}
    >
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
          padding: tall ? '300px 150px' : '130px 150px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: tall ? 'center' : undefined,
          zIndex: 1,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: tall ? 36 : 28 }}>
          <div
            style={{
              width: logo,
              height: logo,
              borderRadius: Math.round(logo * 0.24),
              background: '#ffffff',
              border: `3px solid ${pal.tileBorder}`,
              overflow: 'hidden',
              flexShrink: 0,
            }}
          >
            <Img src={staticFile('omniusgrid-logo.png')} style={{ width: logo, height: logo }} />
          </div>
          <span style={{ fontSize: tall ? 102 : 76, color: pal.text, letterSpacing: -1.5 }}>
            <Wordmark />
          </span>
        </div>
        {tall ? <div style={{ height: 170 }} /> : <div style={{ flex: 1 }} />}
        {headline}
        <div
          style={{
            marginTop: 80,
            ...(tall
              ? { transform: `scale(${tallScale})`, transformOrigin: 'left top', marginBottom: 60 }
              : {}),
          }}
        >
          <Window title={winTitle} img={img} w={imgW} />
        </div>
        {tall ? <div style={{ height: 190 }} /> : <div style={{ flex: 1 }} />}
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'space-between',
            gap: 60,
          }}
        >
          <div
            style={{
              fontSize: tall ? 62 : 52,
              fontWeight: 700,
              color: pal.kicker,
              lineHeight: 1.35,
              maxWidth: tall ? 1620 : 1450,
            }}
          >
            {kicker}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
            <span
              style={{
                fontSize: (tall ? 72 : 56) * 0.5,
                fontWeight: 500,
                color: pal.textSecondary,
              }}
            >
              by
            </span>
            <div
              style={{
                background: '#ffffff',
                borderRadius: 999,
                padding: `${(tall ? 72 : 56) * 0.22}px ${(tall ? 72 : 56) * 0.5}px`,
                border: `3px solid ${pal.pillBorder}`,
                display: 'flex',
                alignItems: 'center',
              }}
            >
              <Img src={staticFile('soundsafe-logo.png')} style={{ height: tall ? 72 : 56 }} />
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const H: React.FC<{ children: React.ReactNode; size?: number }> = ({ children, size = 130 }) => {
  const pal = React.useContext(PalCtx);
  const tallScale = React.useContext(TallCtx);
  return (
    <div
      style={{
        fontSize: Math.round(size * (tallScale > 0 ? Math.min(tallScale, 1.1) : 1)),
        fontWeight: 800,
        color: pal.text,
        letterSpacing: -3,
        lineHeight: 1.12,
      }}
    >
      {children}
    </div>
  );
};

const B: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span style={{ color: theme.highlight }}>{children}</span>
);

/** 1 — the alarm row */
export const RealScreen1: React.FC = () => (
  <RSCard
    headline={
      <H>
        This row knew before
        <br />
        <B>your morning meeting did.</B>
      </H>
    }
    kicker={<>Live alarms, correlated with the machines that raised them.</>}
    winTitle="Dashboard — Active Alarms"
    img="alarms"
    imgW={1740}
  />
);

/** 2 — the OEE card */
export const RealScreen2: React.FC = () => (
  <RSCard
    headline={
      <H size={150}>
        78% isn't a grade.
        <br />
        <B>It's a to-do list.</B>
      </H>
    }
    kicker={<>OEE live, per asset — and the "why" is one question away.</>}
    winTitle="OEE — last 24 hours"
    img="oee-overall"
    imgW={1120}
  />
);

/** 3 — the Kanban card */
export const RealScreen3: React.FC = () => (
  <RSCard
    headline={
      <H size={150}>
        Nobody typed
        <br />
        <B>this ticket.</B>
      </H>
    }
    kicker={<>Dispatched straight from an answer — owner, priority and SAP work order attached.</>}
    winTitle="Operations Board"
    img="kanban-card"
    imgW={820}
  />
);

/** 4 — the intake analysis */
export const RealScreen4: React.FC = () => (
  <RSCard
    headline={
      <H size={140}>
        Nobody reads 1,412 rows.
        <br />
        <B>We read 1,412 rows.</B>
      </H>
    }
    kicker={<>Drop the file — analyzed, correlated and risk-scored in minutes.</>}
    winTitle="Intake Inbox"
    img="intake-head"
    imgW={1520}
  />
);

/** 5 — recommended actions */
export const RealScreen5: React.FC = () => (
  <RSCard
    headline={
      <H size={150}>
        Answers arrive
        <br />
        <B>with chores attached.</B>
      </H>
    }
    kicker={<>Recommended actions on every answer — approve once, dispatched everywhere.</>}
    winTitle="Correlation AI — analysis session"
    img="actions"
    imgW={1640}
  />
);

/** 6 — the ERP roster */
export const RealScreen6: React.FC = () => (
  <RSCard
    headline={
      <H>
        SAP, Oracle and NetSuite,
        <br />
        <B>agreeing for once.</B>
      </H>
    }
    kicker={<>Seven ERPs, synced live — not exported nightly.</>}
    winTitle="ERP Integrations"
    img="erp-rows"
    imgW={1660}
  />
);

/** 7 — the detention banner */
export const RealScreen7: React.FC = () => (
  <RSCard
    headline={
      <H size={124}>
        Caught: $525 in detention —
        <br />
        <B>before it hit the invoice.</B>
      </H>
    }
    kicker={<>Detention flagged while the trailer is still in the yard — not on the invoice.</>}
    winTitle="Yard Management — live"
    img="yard-stats"
    imgW={1240}
  />
);

/** 8 — live telemetry */
export const RealScreen8: React.FC = () => (
  <RSCard
    headline={
      <H size={140}>
        Bearings can't talk.
        <br />
        <B>They vibrate. We listen.</B>
      </H>
    }
    kicker={<>Live vibration, temperature and load — wear caught weeks before it scraps parts.</>}
    winTitle="Asset — Vibration Sensor, CNC Spindle"
    img="telemetry-card"
    imgW={1240}
  />
);

// light + story variants
export const RealScreen1Light = light(RealScreen1);
export const RealScreen2Light = light(RealScreen2);
export const RealScreen3Light = light(RealScreen3);
export const RealScreen4Light = light(RealScreen4);
export const RealScreen5Light = light(RealScreen5);
export const RealScreen6Light = light(RealScreen6);
export const RealScreen7Light = light(RealScreen7);
export const RealScreen8Light = light(RealScreen8);
export const RealScreen1Tall = tallVariant(RealScreen1);
export const RealScreen2Tall = tallVariant(RealScreen2);
export const RealScreen3Tall = tallVariant(RealScreen3);
export const RealScreen4Tall = tallVariant(RealScreen4);
export const RealScreen5Tall = tallVariant(RealScreen5);
export const RealScreen6Tall = tallVariant(RealScreen6);
export const RealScreen7Tall = tallVariant(RealScreen7);
export const RealScreen8Tall = tallVariant(RealScreen8);
export const RealScreen1TallLight = tallVariant(RealScreen1Light);
export const RealScreen2TallLight = tallVariant(RealScreen2Light);
export const RealScreen3TallLight = tallVariant(RealScreen3Light);
export const RealScreen4TallLight = tallVariant(RealScreen4Light);
export const RealScreen5TallLight = tallVariant(RealScreen5Light);
export const RealScreen6TallLight = tallVariant(RealScreen6Light);
export const RealScreen7TallLight = tallVariant(RealScreen7Light);
export const RealScreen8TallLight = tallVariant(RealScreen8Light);
