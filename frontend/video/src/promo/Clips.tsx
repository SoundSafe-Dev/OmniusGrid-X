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
import { Wordmark } from '../components/Wordmark';

/**
 * Micro-demo clips — ORIGINAL 9:16 motion graphics built from the brand
 * language (question bubble, source chips, connectors, GO badge, counters).
 * No demo-video footage. 2160x3840 @30fps; delivered 1080x1920 (--scale=0.5).
 */

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
const GREEN = '#4ade80';

const pop = (frame: number, fps: number, at: number) =>
  spring({ frame: frame - at, fps, config: { damping: 12, stiffness: 160 }, durationInFrames: 30 });

const fadeUp = (frame: number, at: number, dist = 60) => ({
  opacity: interpolate(frame, [at, at + 18], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  }),
  transform: `translateY(${interpolate(frame, [at, at + 18], [dist, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })}px)`,
});

const Shell: React.FC<{ hook: React.ReactNode; children: React.ReactNode }> = ({
  hook,
  children,
}) => (
  <AbsoluteFill style={{ background: theme.darkBg, fontFamily: theme.fontFamily }}>
    <AbsoluteFill
      style={{
        backgroundImage: `linear-gradient(${theme.darkBorder} 1px, transparent 1px), linear-gradient(90deg, ${theme.darkBorder} 1px, transparent 1px)`,
        backgroundSize: '120px 120px',
        opacity: 0.22,
        maskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
        WebkitMaskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
      }}
    />
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '300px 170px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        zIndex: 1,
      }}
    >
      <div
        style={{
          fontSize: 118,
          fontWeight: 800,
          color: theme.darkText,
          letterSpacing: -2.5,
          lineHeight: 1.12,
        }}
      >
        {hook}
      </div>
      <div style={{ height: 150 }} />
      {children}
      <div style={{ height: 190 }} />
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 30 }}>
          <div
            style={{
              width: 108,
              height: 108,
              borderRadius: 26,
              background: '#ffffff',
              overflow: 'hidden',
              flexShrink: 0,
            }}
          >
            <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 108, height: 108 }} />
          </div>
          <span style={{ fontSize: 88, color: theme.darkText, letterSpacing: -1.5 }}>
            <Wordmark />
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
          <span style={{ fontSize: 34, fontWeight: 500, color: theme.darkTextSecondary }}>by</span>
          <div
            style={{
              background: '#ffffff',
              borderRadius: 999,
              padding: '15px 34px',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <Img src={staticFile('soundsafe-logo.png')} style={{ height: 66 }} />
          </div>
        </div>
      </div>
    </div>
  </AbsoluteFill>
);

/** fading brand end-card */
const Outro: React.FC<{ at: number }> = ({ at }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame < at) return null;
  const opacity = interpolate(frame, [at, at + 18], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const s = spring({ frame: frame - at, fps, config: { damping: 16 }, durationInFrames: 40 });
  return (
    <AbsoluteFill
      style={{
        background: theme.darkBg,
        opacity,
        fontFamily: theme.fontFamily,
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 10,
      }}
    >
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${theme.darkBorder} 1px, transparent 1px), linear-gradient(90deg, ${theme.darkBorder} 1px, transparent 1px)`,
          backgroundSize: '120px 120px',
          opacity: 0.22,
          maskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
        }}
      />
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 70,
          transform: `scale(${0.92 + 0.08 * s})`,
          zIndex: 1,
        }}
      >
        <div
          style={{
            width: 300,
            height: 300,
            borderRadius: 66,
            background: '#ffffff',
            overflow: 'hidden',
            boxShadow: '0 0 160px rgba(250,250,250,0.18), 0 50px 140px rgba(0,0,0,0.6)',
          }}
        >
          <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 300, height: 300 }} />
        </div>
        <div style={{ fontSize: 150, color: theme.darkText, letterSpacing: -3, lineHeight: 1 }}>
          <Wordmark />
        </div>
        <div style={{ height: 8, width: 420, borderRadius: 4, background: theme.highlight }} />
        <div
          style={{
            fontSize: 66,
            fontWeight: 700,
            color: theme.darkText,
            textAlign: 'center',
            lineHeight: 1.3,
          }}
        >
          Unleash the power of{' '}
          <span style={{ color: theme.highlight }}>data correlation</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 24, marginTop: 20 }}>
          <span style={{ fontSize: 36, fontWeight: 500, color: theme.darkTextSecondary }}>by</span>
          <div
            style={{
              background: '#ffffff',
              borderRadius: 999,
              padding: '16px 36px',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <Img src={staticFile('soundsafe-logo.png')} style={{ height: 72 }} />
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Chip: React.FC<{ label: string; tone: 'blue' | 'green'; size?: number }> = ({
  label,
  tone,
  size = 52,
}) => {
  const t =
    tone === 'green'
      ? { border: 'rgba(74,222,128,0.5)', bg: 'rgba(74,222,128,0.10)', color: GREEN }
      : { border: 'rgba(59,130,246,0.45)', bg: 'rgba(59,130,246,0.10)', color: theme.highlightSoft };
  return (
    <span
      style={{
        padding: `${Math.round(size * 0.33)}px ${Math.round(size * 0.7)}px`,
        borderRadius: 999,
        border: `4px solid ${t.border}`,
        background: t.bg,
        color: t.color,
        fontSize: size,
        fontWeight: 800,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );
};

const GoBadge: React.FC<{ scale: number; size?: number; label?: string }> = ({
  scale,
  size = 84,
  label = 'GO · 91',
}) => (
  <span
    style={{
      display: 'inline-block',
      transform: `scale(${scale})`,
      fontSize: size,
      fontWeight: 800,
      color: GREEN,
      border: '5px solid rgba(74,222,128,0.55)',
      background: 'rgba(74,222,128,0.14)',
      borderRadius: 24,
      padding: `${size * 0.28}px ${size * 0.65}px`,
      whiteSpace: 'nowrap',
      boxShadow: '0 0 90px rgba(74,222,128,0.25)',
    }}
  >
    {label}
  </span>
);

// ------------------------------------------------------------ clip 1 · ask

const QUESTION = 'What happens if we raise Line 3 output by 20%?';
const SOURCES: [string, 'blue' | 'green', string][] = [
  ['XLSX', 'blue', 'material-forecast_q3.xlsx'],
  ['PDF', 'blue', 'carrier-agreement_2026.pdf'],
  ['● LIVE', 'green', 'Lines 1–3 stream'],
];
const TYPE_START = 25;
const TYPE_CPS = 0.45; // chars per frame
const SRC_AT = [150, 185, 220];
const GO_AT = 268;
const ACT_AT = 300;

export const ClipAsk: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const typed = QUESTION.slice(
    0,
    Math.max(0, Math.min(QUESTION.length, Math.floor((frame - TYPE_START) * 0.54)))
  );
  const typingDone = typed.length >= QUESTION.length;
  return (
    <Shell
      hook={
        <>
          Watch a question
          <br />
          <span style={{ color: theme.highlight }}>get its receipts.</span>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 60 }}>
        {/* the question bubble, typing */}
        <div
          style={{
            alignSelf: 'flex-end',
            maxWidth: '92%',
            background: '#ffffff',
            color: theme.darkBg,
            borderRadius: '36px 36px 10px 36px',
            padding: '40px 60px',
            fontSize: 64,
            fontWeight: 600,
            minHeight: 170,
            ...fadeUp(frame, 8),
          }}
        >
          {typed}
          {!typingDone && frame > TYPE_START && (
            <span style={{ opacity: frame % 16 < 8 ? 1 : 0 }}>|</span>
          )}
        </div>
        {/* sources cascade in */}
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {SOURCES.map(([tag, tone, file], i) => (
            <React.Fragment key={tag}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 44,
                  ...fadeUp(frame, SRC_AT[i]),
                }}
              >
                <div style={{ width: 300, display: 'flex', justifyContent: 'center', flexShrink: 0 }}>
                  <Chip label={tag} tone={tone} />
                </div>
                <span style={{ fontFamily: MONO, fontSize: 56, fontWeight: 700, color: theme.darkText }}>
                  {file}
                </span>
              </div>
              {i < SOURCES.length - 1 && (
                <div
                  style={{
                    height: 44,
                    marginLeft: 150,
                    borderLeft: '5px dashed rgba(59,130,246,0.45)',
                    opacity: interpolate(frame, [SRC_AT[i + 1] - 10, SRC_AT[i + 1]], [0, 1], {
                      extrapolateLeft: 'clamp',
                      extrapolateRight: 'clamp',
                    }),
                  }}
                />
              )}
            </React.Fragment>
          ))}
        </div>
        {/* verdict */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 50, minHeight: 200 }}>
          {frame >= GO_AT && <GoBadge scale={pop(frame, fps, GO_AT)} />}
          {frame >= ACT_AT && (
            <span
              style={{
                fontSize: 56,
                fontWeight: 700,
                color: '#0a0a0a',
                background: theme.highlightSoft,
                borderRadius: 999,
                padding: '26px 54px',
                ...fadeUp(frame, ACT_AT, 30),
              }}
            >
              Green-light +20% on Line 3
            </span>
          )}
        </div>
      </div>
      <Outro at={375} />
    </Shell>
  );
};
export const CLIP_ASK_DURATION = 465;

// ------------------------------------------------------ clip 2 · detention

const DWELL_TARGET_MIN = 240; // 4h
const COUNT_END = 150; // frame when dwell reaches 4h
const FLAG_AT = 96; // alert fires at ~2h36m
const CLIP2_DUR = 405;

export const ClipDetention: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const mins = Math.round(
    interpolate(frame, [15, COUNT_END], [0, DWELL_TARGET_MIN], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    })
  );
  const hours = Math.floor(mins / 60);
  const mm = String(mins % 60).padStart(2, '0');
  // fee starts accruing past 2h free time
  const fee = Math.round(
    interpolate(mins, [120, DWELL_TARGET_MIN], [0, 450], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    })
  );
  const flagged = frame >= FLAG_AT;
  return (
    <Shell
      hook={
        <>
          Yard data,
          <br />
          <span style={{ color: theme.highlight }}>read on time.</span>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 70 }}>
        {/* trailer row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 40,
            border: `4px solid ${theme.darkBorder}`,
            borderRadius: 28,
            padding: '38px 54px',
            ...fadeUp(frame, 6),
          }}
        >
          <span style={{ fontSize: 46, fontWeight: 800, letterSpacing: 4, color: theme.highlightSoft }}>
            YMS
          </span>
          <span style={{ fontFamily: MONO, fontSize: 60, fontWeight: 700, color: theme.darkText }}>
            TR-2024-004
          </span>
          <span style={{ fontSize: 50, color: theme.darkTextSecondary }}>Dock 4</span>
          <span style={{ marginLeft: 'auto', fontFamily: MONO, fontSize: 60, fontWeight: 800, color: theme.darkText }}>
            {hours}h {mm}m
          </span>
        </div>
        {/* the fee, building */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 44, ...fadeUp(frame, 20) }}>
          <span style={{ fontSize: 60, fontWeight: 600, color: theme.darkTextSecondary }}>
            Detention accruing
          </span>
          <span
            style={{
              fontFamily: MONO,
              fontSize: 170,
              fontWeight: 800,
              color: fee > 0 ? '#f87171' : theme.darkText,
            }}
          >
            ${fee}
          </span>
        </div>
        {/* the flag — fired long before the fee */}
        <div style={{ minHeight: 260 }}>
          {flagged && (
            <div
              style={{
                transform: `scale(${pop(frame, fps, FLAG_AT)})`,
                transformOrigin: 'left center',
                display: 'flex',
                flexDirection: 'column',
                gap: 30,
                border: '4px solid rgba(74,222,128,0.5)',
                background: 'rgba(74,222,128,0.08)',
                borderRadius: 28,
                padding: '44px 54px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 34 }}>
                <Chip label="● FLAGGED" tone="green" size={46} />
                <span style={{ fontSize: 56, fontWeight: 700, color: theme.darkText }}>
                  Detention risk — 90 min before billing
                </span>
              </div>
              <span style={{ fontSize: 48, color: 'rgba(250,250,250,0.85)' }}>
                Pull-out scheduled · dispute-ready timestamps attached
              </span>
            </div>
          )}
        </div>
      </div>
      <Outro at={315} />
    </Shell>
  );
};
export const CLIP_DETENTION_DURATION = CLIP2_DUR;

// -------------------------------------------------- clip 3 · couples therapy

const MEET_AT = 90;
const LINK_AT = 130;
const GO3_AT = 175;

export const ClipTherapy: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const meet = spring({ frame: frame - MEET_AT, fps, config: { damping: 16 }, durationInFrames: 40 });
  const apart = 560 * (1 - Math.min(1, Math.max(0, meet)));
  const linkW = interpolate(frame, [LINK_AT, LINK_AT + 26], [0, 320], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const dots = (at: number) =>
    frame < MEET_AT ? ['', '.', '..', '...'][Math.floor((frame - at) / 12) % 4] : '';
  return (
    <Shell
      hook={
        <>
          Couples therapy
          <br />
          <span style={{ color: theme.highlight }}>for industrial data.</span>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 90, alignItems: 'center' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '100%',
            minHeight: 320,
          }}
        >
          {/* ERP side */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 24,
              transform: `translateX(${-apart / 2}px)`,
            }}
          >
            <span style={{ fontSize: 42, minHeight: 60, color: theme.darkTextSecondary, fontFamily: MONO }}>
              {dots(0)}
            </span>
            <Chip label="XLSX" tone="blue" size={72} />
            <span style={{ fontSize: 42, color: theme.darkTextSecondary }}>your ERP</span>
          </div>
          {/* the link, drawn when they meet */}
          <div
            style={{
              width: linkW,
              borderTop: '6px dashed rgba(59,130,246,0.55)',
              margin: '0 30px',
              marginBottom: 60,
            }}
          />
          {/* machines side */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 24,
              transform: `translateX(${apart / 2}px)`,
            }}
          >
            <span style={{ fontSize: 42, minHeight: 60, color: theme.darkTextSecondary, fontFamily: MONO }}>
              {dots(6)}
            </span>
            <Chip label="● LIVE" tone="green" size={72} />
            <span style={{ fontSize: 42, color: theme.darkTextSecondary }}>your machines</span>
          </div>
        </div>
        <div style={{ minHeight: 240 }}>
          {frame >= GO3_AT && <GoBadge scale={pop(frame, fps, GO3_AT)} size={100} />}
        </div>
        <div
          style={{
            fontSize: 66,
            fontWeight: 700,
            color: theme.highlightSoft,
            textAlign: 'center',
            lineHeight: 1.35,
            ...fadeUp(frame, GO3_AT + 30),
          }}
        >
          Your ERP talks. Your machines talk.
          <br />
          Now — to each other.
        </div>
      </div>
      <Outro at={255} />
    </Shell>
  );
};
export const CLIP_THERAPY_DURATION = 345;
