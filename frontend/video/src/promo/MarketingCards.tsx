import React from 'react';
import { Img, staticFile } from 'remotion';
import { theme } from '../theme';
import { Wordmark } from '../components/Wordmark';
import { Base, BySoundSafe } from './PromoCards';

/**
 * Witty social cards — 2160x2160, delivered 1080x1080 in out/marketing.
 * Each card: one sharp line, one real product artifact as the proof.
 */

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
const GREEN = '#4ade80';

/** true when rendering the 9:16 story variant — adds UI-safe top/bottom padding */
const TallCtx = React.createContext(0);

const Chip: React.FC<{ label: string; tone?: 'blue' | 'green' | 'neutral'; size?: number }> = ({
  label,
  tone = 'neutral',
  size = 44,
}) => {
  const t =
    tone === 'green'
      ? { border: 'rgba(74,222,128,0.5)', bg: 'rgba(74,222,128,0.08)', color: GREEN, w: 700 }
      : tone === 'blue'
        ? {
            border: 'rgba(59,130,246,0.45)',
            bg: 'rgba(59,130,246,0.08)',
            color: theme.highlightSoft,
            w: 700,
          }
        : { border: theme.darkBorder, bg: 'transparent', color: theme.darkTextSecondary, w: 600 };
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
      color: GREEN,
      border: '3px solid rgba(74,222,128,0.55)',
      background: 'rgba(74,222,128,0.14)',
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
  <Base>
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
            overflow: 'hidden',
            flexShrink: 0,
          }}
        >
          <Img src={staticFile('omniusgrid-logo.png')} style={{ width: logo, height: logo }} />
        </div>
        <span style={{ fontSize: tall ? 102 : 76, color: theme.darkText, letterSpacing: -1.5 }}>
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
            color: theme.highlightSoft,
            lineHeight: 1.35,
            maxWidth: tall ? 1620 : 1450,
          }}
        >
          {kicker}
        </div>
        <BySoundSafe size={tall ? 72 : 56} />
      </div>
    </div>
  </Base>
  );
};

const H: React.FC<{ children: React.ReactNode; size?: number }> = ({ children, size = 150 }) => {
  const tallScale = React.useContext(TallCtx);
  return (
    <div
      style={{
        fontSize: Math.round(size * (tallScale > 0 ? tallScale : 1)),
        fontWeight: 800,
        color: theme.darkText,
        letterSpacing: -3,
        lineHeight: 1.1,
      }}
    >
      {children}
    </div>
  );
};

/** 1 — couples therapy */
export const Marketing1: React.FC = () => (
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
        <div style={{ width: 120, borderTop: '5px dashed rgba(59,130,246,0.5)' }} />
        <Chip label="● LIVE" tone="green" size={52} />
        <span style={{ fontSize: 64, color: theme.darkTextSecondary }}>→</span>
        <GoBadge size={52} />
      </div>
    }
  />
);

/** 2 — FINAL_v7 */
export const Marketing2: React.FC = () => (
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
          background: '#ffffff',
          color: theme.darkBg,
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
export const Marketing3: React.FC = () => (
  <MCard
    headline={
      <div>
        <div
          style={{
            fontSize: 110,
            fontWeight: 800,
            color: theme.darkTextSecondary,
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
            color: theme.darkText,
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
export const Marketing4: React.FC = () => (
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
export const Marketing5: React.FC = () => (
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
              border: `3px solid ${theme.darkBorder}`,
              color: theme.darkTextSecondary,
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

/** 7 — trust issues */
export const Marketing7: React.FC = () => (
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
        <span style={{ fontSize: 60, color: theme.darkTextSecondary }}>→</span>
        <Chip label="one context" tone="blue" size={50} />
      </div>
    }
  />
);

/** 8 — dashboards */
export const Marketing8: React.FC = () => (
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
            color: '#0a0a0a',
            background: theme.highlightSoft,
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
            color: 'rgba(250,250,250,0.9)',
            border: `3px solid ${theme.darkBorder}`,
            borderRadius: 999,
            padding: '20px 44px',
          }}
        >
          Kanban task → Maintenance <span style={{ color: GREEN }}>✓ dispatched</span>
        </span>
      </div>
    }
  />
);

/** 9 — tribal knowledge */
export const Marketing9: React.FC = () => (
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
          background: '#ffffff',
          color: theme.darkBg,
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
export const Marketing10: React.FC = () => (
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
            color: theme.darkTextSecondary,
          }}
        >
          Reasoning
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 28, flexWrap: 'wrap' }}>
          <Chip label="XLSX" tone="blue" size={48} />
          <span style={{ fontSize: 54, color: theme.darkTextSecondary }}>→</span>
          <Chip label="PDF" tone="blue" size={48} />
          <span style={{ fontSize: 54, color: theme.darkTextSecondary }}>→</span>
          <Chip label="● LIVE" tone="green" size={48} />
          <span style={{ fontSize: 54, color: theme.darkTextSecondary }}>→</span>
          <GoBadge size={48} />
        </div>
      </div>
    }
  />
);

const tallVariant = (C: React.FC, scale = 1.12): React.FC => {
  const T: React.FC = () => (
    <TallCtx.Provider value={scale}>
      <C />
    </TallCtx.Provider>
  );
  return T;
};

/** 6 — detention */
export const Marketing6: React.FC = () => (
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
              border: `3px solid ${theme.darkBorder}`,
              borderRadius: 20,
              padding: '24px 38px',
            }}
          >
            <span
              style={{
                fontSize: 38,
                fontWeight: 800,
                letterSpacing: 3,
                color: theme.highlightSoft,
              }}
            >
              {sys}
            </span>
            <span style={{ fontFamily: MONO, fontSize: 44, fontWeight: 700, color: theme.darkText }}>
              {id}
            </span>
            <span style={{ fontSize: 40, color: theme.darkTextSecondary }}>{mid}</span>
            <span style={{ marginLeft: 'auto', fontSize: 40, fontWeight: 700, color: GREEN }}>
              {status}
            </span>
          </div>
        ))}
      </div>
    }
  />
);

// 9:16 story variants — same cards, UI-safe vertical padding
export const Marketing1Tall = tallVariant(Marketing1);
export const Marketing2Tall = tallVariant(Marketing2, 1.05);
export const Marketing3Tall = tallVariant(Marketing3);
export const Marketing4Tall = tallVariant(Marketing4);
export const Marketing5Tall = tallVariant(Marketing5);
export const Marketing6Tall = tallVariant(Marketing6);
export const Marketing7Tall = tallVariant(Marketing7, 1.08);
export const Marketing8Tall = tallVariant(Marketing8);
export const Marketing9Tall = tallVariant(Marketing9);
export const Marketing10Tall = tallVariant(Marketing10);
