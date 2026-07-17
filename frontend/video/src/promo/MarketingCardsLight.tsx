import React from 'react';
import { AbsoluteFill, Img, staticFile } from 'remotion';
import { theme } from '../theme';
import { Wordmark } from '../components/Wordmark';

/**
 * Light-theme duplicates of the witty social cards in MarketingCards.tsx —
 * same copy and layout, light palette. Keep the two files in sync.
 */

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

/** true when rendering the 9:16 story variant — adds UI-safe top/bottom padding */
const TallCtx = React.createContext(0);

const L = {
  bg: '#f7f7f8',
  gridLine: '#e6e6ea',
  text: '#141414',
  textSecondary: '#5c5c62',
  border: '#e2e2e6',
  accentText: '#2563eb',
  accentBorder: 'rgba(37,99,235,0.35)',
  accentBg: 'rgba(59,130,246,0.08)',
  green: '#16a34a',
  greenBorder: 'rgba(22,163,74,0.45)',
  greenBg: 'rgba(22,163,74,0.07)',
  bubbleBg: '#171717',
  bubbleText: '#ffffff',
  primaryBg: '#2563eb',
  primaryText: '#ffffff',
};

const LBase: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill
    style={{
      background: L.bg,
      fontFamily: theme.fontFamily,
      alignItems: 'center',
      justifyContent: 'center',
    }}
  >
    <AbsoluteFill
      style={{
        backgroundImage: `linear-gradient(${L.gridLine} 1px, transparent 1px), linear-gradient(90deg, ${L.gridLine} 1px, transparent 1px)`,
        backgroundSize: '120px 120px',
        opacity: 0.6,
        maskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
        WebkitMaskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
      }}
    />
    {children}
  </AbsoluteFill>
);

const BySoundSafe: React.FC<{ size?: number }> = ({ size = 56 }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
    <span style={{ fontSize: size * 0.5, fontWeight: 500, color: L.textSecondary }}>by</span>
    <div
      style={{
        background: '#ffffff',
        borderRadius: 999,
        padding: `${size * 0.22}px ${size * 0.5}px`,
        border: `3px solid ${L.border}`,
        display: 'flex',
        alignItems: 'center',
      }}
    >
      <Img src={staticFile('soundsafe-logo.png')} style={{ height: size }} />
    </div>
  </div>
);

const Chip: React.FC<{ label: string; tone?: 'blue' | 'green' | 'neutral'; size?: number }> = ({
  label,
  tone = 'neutral',
  size = 44,
}) => {
  const t =
    tone === 'green'
      ? { border: L.greenBorder, bg: L.greenBg, color: L.green, w: 700 }
      : tone === 'blue'
        ? { border: L.accentBorder, bg: L.accentBg, color: L.accentText, w: 700 }
        : { border: L.border, bg: 'transparent', color: L.textSecondary, w: 600 };
  return (
    <span
      style={{
        padding: `${Math.round(size * 0.33)}px ${Math.round(size * 0.8)}px`,
        borderRadius: 999,
        border: `3px solid ${t.border}`,
        background: t.bg,
        color: t.color,
        fontSize: size,
        fontWeight: t.w,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );
};

const GoBadge: React.FC<{ size?: number }> = ({ size = 48 }) => (
  <span
    style={{
      fontSize: size,
      fontWeight: 800,
      color: L.green,
      border: `3px solid ${L.greenBorder}`,
      background: L.greenBg,
      borderRadius: 16,
      padding: `${size * 0.28}px ${size * 0.7}px`,
      whiteSpace: 'nowrap',
    }}
  >
    GO · 91
  </span>
);

const MCard: React.FC<{
  headline: React.ReactNode;
  kicker: React.ReactNode;
  artifact: React.ReactNode;
}> = ({ headline, kicker, artifact }) => {
  const tallScale = React.useContext(TallCtx);
  const tall = tallScale > 0;
  const logo = tall ? 126 : 92;
  return (
  <LBase>
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
            border: `3px solid ${L.border}`,
            overflow: 'hidden',
            flexShrink: 0,
          }}
        >
          <Img src={staticFile('omniusgrid-logo.png')} style={{ width: logo, height: logo }} />
        </div>
        <span style={{ fontSize: tall ? 102 : 76, color: L.text, letterSpacing: -1.5 }}>
          <Wordmark />
        </span>
      </div>
      {tall ? <div style={{ height: 190 }} /> : <div style={{ flex: 1 }} />}
      {headline}
      <div
        style={{
          marginTop: 90,
          ...(tall
            ? { transform: `scale(${tallScale})`, transformOrigin: 'left top', marginBottom: 70 }
            : {}),
        }}
      >
        {artifact}
      </div>
      {tall ? <div style={{ height: 210 }} /> : <div style={{ flex: 1 }} />}
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
            color: L.accentText,
            lineHeight: 1.35,
            maxWidth: tall ? 1620 : 1450,
          }}
        >
          {kicker}
        </div>
        <BySoundSafe size={tall ? 72 : 56} />
      </div>
    </div>
  </LBase>
  );
};

const H: React.FC<{ children: React.ReactNode; size?: number }> = ({ children, size = 150 }) => {
  const tallScale = React.useContext(TallCtx);
  return (
    <div
      style={{
        fontSize: Math.round(size * (tallScale > 0 ? tallScale : 1)),
        fontWeight: 800,
        color: L.text,
        letterSpacing: -3,
        lineHeight: 1.1,
      }}
    >
      {children}
    </div>
  );
};

/** 1 — couples therapy */
export const Marketing1Light: React.FC = () => (
  <MCard
    headline={
      <H>
        Your ERP talks.
        <br />
        Your machines talk.
        <br />
        <span style={{ color: theme.highlight }}>Not to each other.</span>
      </H>
    }
    kicker={<>OmniusGrid — couples therapy for industrial data.</>}
    artifact={
      <div style={{ display: 'flex', alignItems: 'center', gap: 34 }}>
        <Chip label="XLSX" tone="blue" size={52} />
        <div style={{ width: 120, borderTop: `5px dashed ${L.accentBorder}` }} />
        <Chip label="● LIVE" tone="green" size={52} />
        <span style={{ fontSize: 64, color: L.textSecondary }}>→</span>
        <GoBadge size={52} />
      </div>
    }
  />
);

/** 2 — FINAL_v7 */
export const Marketing2Light: React.FC = () => (
  <MCard
    headline={
      <H size={140}>
        Retire
        <br />
        <span style={{ fontFamily: MONO, fontSize: '0.74em', letterSpacing: 0 }}>
          capacity-plan_FINAL_v7.xlsx
        </span>
      </H>
    }
    kicker={
      <>
        Ask the question instead — the answer shows its reasoning, carries a
        score, and ships with an action.
      </>
    }
    artifact={
      <div
        style={{
          alignSelf: 'flex-start',
          background: L.bubbleBg,
          color: L.bubbleText,
          borderRadius: '32px 32px 10px 32px',
          padding: '34px 54px',
          fontSize: 58,
          fontWeight: 600,
          maxWidth: 1700,
        }}
      >
        What happens if we raise Line 3 output by 20%?
      </div>
    }
  />
);

/** 3 — meetings */
export const Marketing3Light: React.FC = () => (
  <MCard
    headline={
      <div>
        <div
          style={{
            fontSize: 110,
            fontWeight: 800,
            color: L.textSecondary,
            letterSpacing: -2,
            lineHeight: 1.18,
          }}
        >
          Six people.
          <br />
          Forty-five minutes.
          <br />
          No answer.
        </div>
        <div
          style={{
            marginTop: 70,
            fontSize: 150,
            fontWeight: 800,
            color: L.text,
            letterSpacing: -3,
            lineHeight: 1.12,
          }}
        >
          One question.
          <br />
          <span style={{ color: theme.highlight }}>Nine seconds.</span>
        </div>
      </div>
    }
    kicker={<>No meetings, no digging.</>}
    artifact={<GoBadge size={56} />}
  />
);

/** 4 — the PDF knows */
export const Marketing4Light: React.FC = () => (
  <MCard
    headline={
      <H size={140}>
        Somewhere in your files,
        <br />
        a PDF knows
        <br />
        <span style={{ color: theme.highlight }}>why scrap jumped.</span>
      </H>
    }
    kicker={
      <>
        We speak PDF. And XLSX, JPG, WAV —
        <br />
        and live machine data. Fluently.
      </>
    }
    artifact={
      <div style={{ display: 'flex', gap: 26, flexWrap: 'wrap' }}>
        <Chip label="XLSX" tone="blue" size={50} />
        <Chip label="PDF" tone="blue" size={50} />
        <Chip label="JPG" tone="blue" size={50} />
        <Chip label="WAV" tone="blue" size={50} />
        <Chip label="● LIVE" tone="green" size={50} />
      </div>
    }
  />
);

/** 5 — gut feel */
export const Marketing5Light: React.FC = () => (
  <MCard
    headline={
      <H>
        Gut feel is not
        <br />
        <span style={{ color: theme.highlight }}>a data source.</span>
      </H>
    }
    kicker={
      <>
        Decisions on evidence —
        <br />
        reasoning shown, score attached, action ready.
      </>
    }
    artifact={
      <div style={{ display: 'flex', gap: 26, flexWrap: 'wrap', alignItems: 'center' }}>
        {['hunches', 'vibes'].map((w) => (
          <span
            key={w}
            style={{
              padding: '17px 40px',
              borderRadius: 999,
              border: `3px solid ${L.border}`,
              color: L.textSecondary,
              fontSize: 50,
              fontWeight: 600,
              textDecoration: 'line-through',
              textDecorationThickness: 5,
            }}
          >
            {w}
          </span>
        ))}
        <Chip label="XLSX" tone="blue" size={50} />
        <Chip label="PDF" tone="blue" size={50} />
        <Chip label="● LIVE" tone="green" size={50} />
      </div>
    }
  />
);

/** 6 — detention */
export const Marketing6Light: React.FC = () => (
  <MCard
    headline={
      <H size={132}>
        A detention fee is just
        <br />
        yard data{' '}
        <span style={{ color: theme.highlight }}>you read too late.</span>
      </H>
    }
    kicker={
      <>
        TMS and YMS in one picture —
        <br />
        flagged while there's still time to act.
      </>
    }
    artifact={
      <div style={{ display: 'flex', flexDirection: 'column', gap: 22, maxWidth: 1500 }}>
        {[
          ['TMS', 'SHP-2214', '2 loads/wk', '● covered'],
          ['YMS', 'Dock 4', 'dwell 6 h', '● clear'],
        ].map(([sys, id, mid, status]) => (
          <div
            key={sys}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 28,
              border: `3px solid ${L.border}`,
              background: '#ffffff',
              borderRadius: 20,
              padding: '24px 38px',
            }}
          >
            <span
              style={{
                fontSize: 38,
                fontWeight: 800,
                letterSpacing: 3,
                color: L.accentText,
              }}
            >
              {sys}
            </span>
            <span style={{ fontFamily: MONO, fontSize: 44, fontWeight: 700, color: L.text }}>
              {id}
            </span>
            <span style={{ fontSize: 40, color: L.textSecondary }}>{mid}</span>
            <span style={{ marginLeft: 'auto', fontSize: 40, fontWeight: 700, color: L.green }}>
              {status}
            </span>
          </div>
        ))}
      </div>
    }
  />
);

/** 7 — trust issues */
export const Marketing7Light: React.FC = () => (
  <MCard
    headline={
      <H size={140}>
        Your data has trust issues.
        <br />
        <span style={{ color: theme.highlight }}>It's been siloed since 2011.</span>
      </H>
    }
    kicker={
      <>
        Seven ERPs, MES, telemetry, GPS fleets —
        <br />
        finally one conversation.
      </>
    }
    artifact={
      <div style={{ display: 'flex', gap: 26, flexWrap: 'wrap', alignItems: 'center' }}>
        <Chip label="SAP" size={50} />
        <Chip label="Oracle" size={50} />
        <Chip label="NetSuite" size={50} />
        <Chip label="+4 more" size={50} />
        <span style={{ fontSize: 60, color: L.textSecondary }}>→</span>
        <Chip label="one context" tone="blue" size={50} />
      </div>
    }
  />
);

/** 8 — dashboards */
export const Marketing8Light: React.FC = () => (
  <MCard
    headline={
      <H size={140}>
        Dashboards show
        <br />
        what happened.
        <br />
        <span style={{ color: theme.highlight }}>We ship what to do next.</span>
      </H>
    }
    kicker={
      <>
        Every answer arrives scored —
        <br />
        with a one-click action attached.
      </>
    }
    artifact={
      <div style={{ display: 'flex', gap: 30, flexWrap: 'wrap', alignItems: 'center' }}>
        <span
          style={{
            fontSize: 50,
            fontWeight: 700,
            color: L.primaryText,
            background: L.primaryBg,
            borderRadius: 999,
            padding: '20px 48px',
          }}
        >
          Approve
        </span>
        <span
          style={{
            fontSize: 46,
            fontWeight: 600,
            color: L.text,
            border: `3px solid ${L.border}`,
            background: '#ffffff',
            borderRadius: 999,
            padding: '20px 44px',
          }}
        >
          Kanban task → Maintenance <span style={{ color: L.green }}>✓ dispatched</span>
        </span>
      </div>
    }
  />
);

/** 9 — tribal knowledge */
export const Marketing9Light: React.FC = () => (
  <MCard
    headline={
      <H size={140}>
        Every shop has someone
        <br />
        who just knows.
        <br />
        <span style={{ color: theme.highlight }}>Now the shop knows too.</span>
      </H>
    }
    kicker={
      <>
        Tribal knowledge, correlated —
        <br />
        photos, audio, files and live telemetry.
      </>
    }
    artifact={
      <div
        style={{
          alignSelf: 'flex-start',
          background: L.bubbleBg,
          color: L.bubbleText,
          borderRadius: '32px 32px 10px 32px',
          padding: '34px 54px',
          fontSize: 58,
          fontWeight: 600,
          maxWidth: 1700,
        }}
      >
        Why does Line 2 squeal on Monday mornings?
      </div>
    }
  />
);

/** 10 — show our work */
export const Marketing10Light: React.FC = () => (
  <MCard
    headline={
      <H>
        We don't do magic.
        <br />
        <span style={{ color: theme.highlight }}>We show our work.</span>
      </H>
    }
    kicker={
      <>
        Reasoning shown, score attached, action ready —
        <br />
        receipts included.
      </>
    }
    artifact={
      <div style={{ display: 'flex', flexDirection: 'column', gap: 26 }}>
        <div
          style={{
            fontSize: 36,
            fontWeight: 700,
            letterSpacing: 6,
            textTransform: 'uppercase',
            color: L.textSecondary,
          }}
        >
          Reasoning
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 28, flexWrap: 'wrap' }}>
          <Chip label="XLSX" tone="blue" size={48} />
          <span style={{ fontSize: 54, color: L.textSecondary }}>→</span>
          <Chip label="PDF" tone="blue" size={48} />
          <span style={{ fontSize: 54, color: L.textSecondary }}>→</span>
          <Chip label="● LIVE" tone="green" size={48} />
          <span style={{ fontSize: 54, color: L.textSecondary }}>→</span>
          <GoBadge size={48} />
        </div>
      </div>
    }
  />
);

// 9:16 story variants — same cards, UI-safe vertical padding
const tallVariant = (C: React.FC, scale = 1.12): React.FC => {
  const T: React.FC = () => (
    <TallCtx.Provider value={scale}>
      <C />
    </TallCtx.Provider>
  );
  return T;
};

export const Marketing1TallLight = tallVariant(Marketing1Light);
export const Marketing2TallLight = tallVariant(Marketing2Light, 1.05);
export const Marketing3TallLight = tallVariant(Marketing3Light);
export const Marketing4TallLight = tallVariant(Marketing4Light);
export const Marketing5TallLight = tallVariant(Marketing5Light);
export const Marketing6TallLight = tallVariant(Marketing6Light);
export const Marketing7TallLight = tallVariant(Marketing7Light, 1.08);
export const Marketing8TallLight = tallVariant(Marketing8Light);
export const Marketing9TallLight = tallVariant(Marketing9Light);
export const Marketing10TallLight = tallVariant(Marketing10Light);
