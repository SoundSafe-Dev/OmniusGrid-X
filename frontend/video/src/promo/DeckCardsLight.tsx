import React from 'react';
import { AbsoluteFill, Img, staticFile } from 'remotion';
import { theme } from '../theme';
import { Wordmark } from '../components/Wordmark';

/**
 * Light-theme duplicates of the two 3-slide decks in DeckCards.tsx —
 * same layout and copy, light palette. Keep the two files in sync when
 * slide content changes.
 */

const L = {
  bg: '#f7f7f8',
  gridLine: '#e6e6ea',
  text: '#141414',
  body: 'rgba(20,20,20,0.78)',
  bodyStrong: 'rgba(20,20,20,0.88)',
  textSecondary: '#5c5c62',
  border: '#e2e2e6',
  cardBg: '#ffffff',
  cardShadow: '0 24px 70px rgba(15,23,42,0.07)',
  accentText: '#2563eb',
  accentBorder: 'rgba(37,99,235,0.35)',
  accentBg: 'rgba(59,130,246,0.08)',
  insetBg: 'rgba(59,130,246,0.06)',
  green: '#16a34a',
  greenBorder: 'rgba(22,163,74,0.45)',
  greenBg: 'rgba(22,163,74,0.07)',
  goBoxBorder: 'rgba(22,163,74,0.4)',
  goBoxBg: 'rgba(22,163,74,0.05)',
  panelBg: '#ffffff',
  panelBorder: '#e2e2e6',
  panelHeaderBg: '#f3f3f5',
  panelShadow: '0 40px 120px rgba(15,23,42,0.14)',
  dot: '#d6d6db',
  bubbleBg: '#171717',
  bubbleText: '#ffffff',
  barTrack: '#e7e7ea',
  primaryBg: '#2563eb',
  primaryText: '#ffffff',
  invBg: '#171717',
  invText: '#ffffff',
};

const Slide: React.FC<{ children: React.ReactNode; pad?: string }> = ({
  children,
  pad = '140px 170px',
}) => (
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
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: pad,
        display: 'flex',
        flexDirection: 'column',
        zIndex: 1,
      }}
    >
      {children}
    </div>
  </AbsoluteFill>
);

const BySoundSafe: React.FC<{ size?: number }> = ({ size = 84 }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 26 }}>
    <span style={{ fontSize: size * 0.5, fontWeight: 500, color: L.textSecondary }}>
      by
    </span>
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

const Overline: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      alignSelf: 'flex-start',
      padding: '18px 48px',
      borderRadius: 999,
      border: `3px solid ${L.border}`,
      color: L.textSecondary,
      fontSize: 42,
      fontWeight: 700,
      letterSpacing: 8,
      textTransform: 'uppercase',
    }}
  >
    {children}
  </div>
);

const Lockup: React.FC<{ size?: number }> = ({ size = 96 }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: size * 0.36 }}>
    <div
      style={{
        width: size * 1.2,
        height: size * 1.2,
        borderRadius: size * 0.28,
        background: '#ffffff',
        border: `3px solid ${L.border}`,
        overflow: 'hidden',
        flexShrink: 0,
      }}
    >
      <Img
        src={staticFile('omniusgrid-logo.png')}
        style={{ width: size * 1.2, height: size * 1.2 }}
      />
    </div>
    <span style={{ fontSize: size, color: L.text, letterSpacing: -2 }}>
      <Wordmark />
    </span>
  </div>
);

const Bullet: React.FC<{ children: React.ReactNode; size?: number }> = ({
  children,
  size = 58,
}) => (
  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 30 }}>
    <div
      style={{
        width: 20,
        height: 20,
        borderRadius: 10,
        background: theme.highlight,
        marginTop: size * 0.42,
        flexShrink: 0,
        boxShadow: '0 0 22px rgba(59,130,246,0.35)',
      }}
    />
    <div
      style={{
        fontSize: size,
        fontWeight: 500,
        color: L.bodyStrong,
        lineHeight: 1.38,
      }}
    >
      {children}
    </div>
  </div>
);

const PanelLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      fontSize: 36,
      fontWeight: 700,
      letterSpacing: 6,
      textTransform: 'uppercase',
      color: L.textSecondary,
    }}
  >
    {children}
  </div>
);

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

const chipTone = (c: string) => {
  if (c.startsWith('●') || c.startsWith('GO'))
    return { border: L.greenBorder, bg: L.greenBg, color: L.green };
  if (['XLSX', 'PDF', 'JPG', 'WAV'].includes(c))
    return { border: L.accentBorder, bg: L.accentBg, color: L.accentText };
  return { border: L.border, bg: 'transparent', color: L.textSecondary };
};

const MiniChip: React.FC<{ label: string; size?: number }> = ({ label, size = 42 }) => {
  const t = chipTone(label);
  return (
    <span
      style={{
        padding: `${Math.round(size * 0.33)}px ${Math.round(size * 0.8)}px`,
        borderRadius: 999,
        border: `3px solid ${t.border}`,
        background: t.bg,
        color: t.color,
        fontSize: size,
        fontWeight: t.color === L.textSecondary ? 600 : 700,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );
};

const SIGNALS: {
  kind: string;
  live?: boolean;
  file: string;
  dept: string;
  text: React.ReactNode;
}[] = [
  {
    kind: 'XLSX',
    file: 'material-forecast_q3.xlsx',
    dept: 'Purchasing',
    text: <>steel + bearing replenishment holds a <b>+20%</b> draw through Q3</>,
  },
  {
    kind: 'PDF',
    file: 'carrier-agreement_2026.pdf',
    dept: 'Logistics',
    text: <>two extra outbound loads per week already covered at contract rate</>,
  },
  {
    kind: 'LIVE',
    live: true,
    file: 'Lines 1–3 stream',
    dept: 'Machines',
    text: <>Line 3 at <b>63% load</b> — Lines 1–2 have room for the changeover dip</>,
  },
];

const CorrelationAnswerLight: React.FC<{ compact?: boolean }> = ({ compact }) => (
  <div
    style={{
      flex: 1,
      borderRadius: 36,
      border: `3px solid ${L.panelBorder}`,
      background: L.panelBg,
      boxShadow: L.panelShadow,
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}
  >
    {/* window header */}
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 18,
        padding: '30px 50px',
        borderBottom: `3px solid ${L.panelBorder}`,
        background: L.panelHeaderBg,
      }}
    >
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{ width: 20, height: 20, borderRadius: 10, background: L.dot }}
        />
      ))}
      <span
        style={{
          marginLeft: 22,
          fontSize: 38,
          fontWeight: 600,
          color: L.textSecondary,
        }}
      >
        Correlation AI — analysis session
      </span>
      <span
        style={{
          marginLeft: 'auto',
          fontSize: 32,
          fontWeight: 700,
          color: L.accentText,
          border: `3px solid ${L.accentBorder}`,
          background: L.accentBg,
          borderRadius: 999,
          padding: '8px 28px',
        }}
      >
        142 files · 6 live streams
      </span>
    </div>
    <div
      style={{
        flex: 1,
        padding: '48px 60px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        gap: 38,
      }}
    >
      {/* the question */}
      <div
        style={{
          alignSelf: 'flex-end',
          maxWidth: '80%',
          background: L.bubbleBg,
          color: L.bubbleText,
          borderRadius: '28px 28px 8px 28px',
          padding: '26px 44px',
          fontSize: 50,
          fontWeight: 600,
        }}
      >
        What happens if we raise Line 3 output by 20%?
      </div>
      {/* the reasoning */}
      <PanelLabel>Reasoning — ingested files × live machine data</PanelLabel>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {SIGNALS.map(({ kind, live, file, dept, text }, i) => (
          <React.Fragment key={kind}>
            <div style={{ display: 'flex', gap: 34, alignItems: 'center' }}>
              <div
                style={{
                  width: 190,
                  textAlign: 'center',
                  fontSize: 32,
                  fontWeight: 800,
                  letterSpacing: 3,
                  color: live ? L.green : L.accentText,
                  border: `3px solid ${live ? L.greenBorder : L.accentBorder}`,
                  background: live ? L.greenBg : L.accentBg,
                  borderRadius: 14,
                  padding: '10px 0',
                  flexShrink: 0,
                }}
              >
                {live ? '● LIVE' : kind}
              </div>
              <div
                style={{
                  fontSize: 44,
                  lineHeight: 1.32,
                  color: L.bodyStrong,
                }}
              >
                <span
                  style={{
                    fontFamily: MONO,
                    fontSize: 40,
                    fontWeight: 700,
                    color: L.text,
                  }}
                >
                  {file}
                </span>{' '}
                <span style={{ color: L.textSecondary }}>({dept})</span> — {text}
              </div>
            </div>
            {i < SIGNALS.length - 1 && (
              <div
                style={{
                  height: 30,
                  marginLeft: 95,
                  borderLeft: `4px dashed ${L.accentBorder}`,
                }}
              />
            )}
          </React.Fragment>
        ))}
      </div>
      {/* the scored answer */}
      <div
        style={{
          display: 'flex',
          gap: 38,
          alignItems: 'flex-start',
          border: `3px solid ${L.goBoxBorder}`,
          background: L.goBoxBg,
          borderRadius: 26,
          padding: '34px 44px',
        }}
      >
        <div
          style={{
            fontSize: 38,
            fontWeight: 800,
            color: L.green,
            border: `3px solid ${L.greenBorder}`,
            background: L.greenBg,
            borderRadius: 14,
            padding: '10px 26px',
            whiteSpace: 'nowrap',
            flexShrink: 0,
          }}
        >
          GO · 91
        </div>
        <div style={{ fontSize: 47, lineHeight: 1.36, color: L.bodyStrong }}>
          <b>Line 3 absorbs +20% without a new bottleneck</b> — materials hold
          through Q3, freight is already contracted, and Lines 1–2 cover the
          changeover dip. Green-light it.
        </div>
      </div>
      {/* the action */}
      <PanelLabel>Actionable insight — one click</PanelLabel>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
        <span
          style={{
            fontSize: 42,
            fontWeight: 700,
            color: L.primaryText,
            background: L.primaryBg,
            borderRadius: 999,
            padding: '18px 42px',
          }}
        >
          Green-light +20% on Line 3
        </span>
        <span
          style={{
            fontSize: 42,
            fontWeight: 600,
            color: L.bodyStrong,
            border: `3px solid ${L.border}`,
            borderRadius: 999,
            padding: '18px 42px',
          }}
        >
          Material orders → Purchasing <span style={{ color: L.green }}>✓ dispatched</span>
        </span>
        {!compact && (
          <span
            style={{
              fontSize: 42,
              fontWeight: 600,
              color: L.textSecondary,
              border: `3px solid ${L.border}`,
              borderRadius: 999,
              padding: '18px 42px',
            }}
          >
            Reserve 2 carrier loads / week
          </span>
        )}
      </div>
    </div>
  </div>
);

// ---------------------------------------------------------------- client

/** C1 light — the problem, in the brand's own words */
export const ClientSlide1Light: React.FC = () => (
  <Slide>
    <Lockup size={84} />
    <div style={{ flex: 1 }} />
    <div
      style={{
        fontSize: 170,
        fontWeight: 800,
        color: L.text,
        letterSpacing: -3,
        lineHeight: 1.12,
      }}
    >
      You cannot make smart decisions with{' '}
      <span
        style={{
          background: L.invBg,
          color: L.invText,
          borderRadius: 28,
          padding: '4px 44px',
          whiteSpace: 'nowrap',
        }}
      >
        scattered data
      </span>
    </div>
    <div
      style={{
        marginTop: 80,
        fontSize: 70,
        fontWeight: 500,
        color: L.body,
        lineHeight: 1.45,
        maxWidth: 3100,
      }}
    >
      Your operation already produces everything you need to know — in ERP
      orders, shipping logs, quality spreadsheets, service PDFs, camera feeds
      and machine telemetry.
      <br />
      <span style={{ whiteSpace: 'nowrap', color: L.text, fontWeight: 600 }}>
        It just never ends up in the same place.
      </span>
    </div>
    <div style={{ flex: 1 }} />
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
      <BySoundSafe size={72} />
    </div>
  </Slide>
);

/** C2 light — what it does: ask about growth, watch it correlate */
export const ClientSlide2Light: React.FC = () => (
  <Slide>
    <Overline>What OmniusGrid does</Overline>
    <div style={{ display: 'flex', gap: 140, marginTop: 90, flex: 1 }}>
      <div
        style={{
          width: 1560,
          display: 'flex',
          flexDirection: 'column',
          gap: 64,
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            fontSize: 138,
            fontWeight: 800,
            color: L.text,
            letterSpacing: -2.5,
            lineHeight: 1.1,
          }}
        >
          Just ask.
          <br />
          <span style={{ color: theme.highlight }}>It correlates.</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 44 }}>
          <Bullet>Drop in the files you already have — Excel, PDFs, photos, audio, video</Bullet>
          <Bullet>Live machine and company data streams in right alongside them</Bullet>
          <Bullet>All departments — logistics, production, financials, sales, quality, admin</Bullet>
          <Bullet>Every answer shows its reasoning — and ships with an action</Bullet>
        </div>
      </div>
      <CorrelationAnswerLight />
    </div>
    <div
      style={{
        marginTop: 80,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <Lockup size={72} />
      <BySoundSafe size={64} />
    </div>
  </Slide>
);

/** C3 light — outcomes + CTA */
export const ClientSlide3Light: React.FC = () => (
  <Slide>
    <Overline>What you get</Overline>
    <div style={{ display: 'flex', gap: 110, marginTop: 130, flex: 1 }}>
      {[
        {
          h: 'Optimized Operations.',
          b: 'See the true load, health and headroom of every line — and grow on evidence, not intuition.',
          cap: '63% load streaming → +20% green-lit. Capacity found, not bought.',
          chips: ['XLSX', 'PDF', '● LIVE telemetry', 'OEE'],
          ui: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
                <MiniChip label="● LIVE" size={28} />
                <span
                  style={{
                    fontFamily: MONO,
                    fontSize: 36,
                    fontWeight: 700,
                    color: L.text,
                  }}
                >
                  Line 3
                </span>
                <span
                  style={{
                    marginLeft: 'auto',
                    fontSize: 36,
                    fontWeight: 800,
                    color: L.text,
                  }}
                >
                  63%{' '}
                  <span style={{ color: L.textSecondary, fontWeight: 500 }}>load</span>
                </span>
              </div>
              <div
                style={{
                  position: 'relative',
                  height: 22,
                  borderRadius: 11,
                  background: L.barTrack,
                }}
              >
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: '63%',
                    borderRadius: 11,
                    background: theme.highlight,
                  }}
                />
                <div
                  style={{
                    position: 'absolute',
                    left: '63%',
                    top: 0,
                    bottom: 0,
                    width: '20%',
                    borderRadius: 11,
                    border: `3px dashed ${L.greenBorder}`,
                    background: L.greenBg,
                  }}
                />
              </div>
              <div style={{ alignSelf: 'flex-end', fontSize: 30, fontWeight: 700, color: L.green }}>
                +20% headroom
              </div>
            </div>
          ),
        },
        {
          h: 'Actionable Insights.',
          b: 'Every answer arrives scored, with recommended actions — assign them to a department in one click.',
          cap: 'One approval — Purchasing and the floor move together.',
          chips: ['GO / risk scores', 'Action approval', 'Kanban dispatch'],
          ui: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
                <MiniChip label="GO · 91" size={28} />
                <span
                  style={{
                    fontSize: 32,
                    fontWeight: 700,
                    color: L.primaryText,
                    background: L.primaryBg,
                    borderRadius: 999,
                    padding: '12px 30px',
                  }}
                >
                  Approve +20% on Line 3
                </span>
              </div>
              <span
                style={{
                  alignSelf: 'flex-start',
                  fontSize: 30,
                  fontWeight: 600,
                  color: L.bodyStrong,
                  border: `3px solid ${L.border}`,
                  borderRadius: 999,
                  padding: '12px 28px',
                }}
              >
                Kanban task → Purchasing <span style={{ color: L.green }}>✓ dispatched</span>
              </span>
            </div>
          ),
        },
        {
          h: 'Maximum Efficiency.',
          b: 'Freight, yard and delivery capacity in one picture — commit to more volume knowing OTIF holds.',
          cap: 'Freight and yard say yes before you commit the volume.',
          chips: ['TMS', 'YMS', 'Detention alerts'],
          ui: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {[
                ['TMS', 'SHP-2214', '2 loads/wk', '● covered'],
                ['YMS', 'Dock 4', 'dwell 6 h', '● clear'],
              ].map(([sys, id, mid, status]) => (
                <div
                  key={sys}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 18,
                    border: `3px solid ${L.border}`,
                    borderRadius: 16,
                    padding: '14px 24px',
                  }}
                >
                  <span
                    style={{
                      fontSize: 26,
                      fontWeight: 800,
                      letterSpacing: 2,
                      color: L.accentText,
                    }}
                  >
                    {sys}
                  </span>
                  <span
                    style={{
                      fontFamily: MONO,
                      fontSize: 30,
                      fontWeight: 700,
                      color: L.text,
                    }}
                  >
                    {id}
                  </span>
                  <span style={{ fontSize: 28, color: L.textSecondary }}>{mid}</span>
                  <span style={{ marginLeft: 'auto', fontSize: 28, fontWeight: 700, color: L.green }}>
                    {status}
                  </span>
                </div>
              ))}
            </div>
          ),
        },
      ].map(({ h, b, cap, chips, ui }) => (
        <div
          key={h}
          style={{
            flex: 1,
            borderRadius: 36,
            border: `3px solid ${L.border}`,
            background: L.cardBg,
            boxShadow: L.cardShadow,
            padding: '100px 80px',
            display: 'flex',
            flexDirection: 'column',
            gap: 56,
          }}
        >
          <div
            style={{
              fontSize: 88,
              fontWeight: 800,
              color: L.text,
              letterSpacing: -1.5,
              lineHeight: 1.12,
            }}
          >
            {h}
          </div>
          <div
            style={{
              fontSize: 56,
              fontWeight: 500,
              color: L.body,
              lineHeight: 1.45,
            }}
          >
            {b}
          </div>
          <div
            style={{
              borderLeft: `8px solid ${theme.highlight}`,
              background: L.insetBg,
              borderRadius: 20,
              padding: '34px 42px',
              display: 'flex',
              flexDirection: 'column',
              gap: 26,
            }}
          >
            <div
              style={{
                fontSize: 34,
                fontWeight: 800,
                letterSpacing: 5,
                textTransform: 'uppercase',
                color: L.accentText,
              }}
            >
              The power-up
            </div>
            {ui}
            <div
              style={{
                fontSize: 40,
                fontWeight: 500,
                color: L.bodyStrong,
                lineHeight: 1.38,
              }}
            >
              {cap}
            </div>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
            {chips.map((c) => (
              <MiniChip key={c} label={c} />
            ))}
          </div>
        </div>
      ))}
    </div>
    <div
      style={{
        marginTop: 110,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <div
        style={{
          padding: '26px 56px',
          borderRadius: 24,
          border: `3px solid ${L.accentBorder}`,
          background: L.accentBg,
          color: L.accentText,
          fontSize: 56,
          fontWeight: 700,
        }}
      >
        ⚡ See your own data correlated
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 60 }}>
        <Lockup size={72} />
        <BySoundSafe size={64} />
      </div>
    </div>
  </Slide>
);

// ---------------------------------------------------------------- investor

/** I1 light — thesis title slide */
export const InvestorSlide1Light: React.FC = () => (
  <Slide>
    <div style={{ flex: 1 }} />
    <div style={{ display: 'flex', alignItems: 'center', gap: 70 }}>
      <div
        style={{
          width: 300,
          height: 300,
          borderRadius: 66,
          background: '#ffffff',
          border: `3px solid ${L.border}`,
          overflow: 'hidden',
          boxShadow: '0 30px 90px rgba(15,23,42,0.18)',
          flexShrink: 0,
        }}
      >
        <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 300, height: 300 }} />
      </div>
      <div style={{ fontSize: 220, color: L.text, letterSpacing: -5, lineHeight: 1 }}>
        <Wordmark />
      </div>
    </div>
    <div
      style={{
        marginTop: 90,
        fontSize: 96,
        fontWeight: 700,
        color: L.text,
        letterSpacing: -1.5,
      }}
    >
      The correlation engine for <span style={{ color: theme.highlight }}>Industry 4.0</span>.
    </div>
    <div
      style={{
        marginTop: 60,
        fontSize: 64,
        fontWeight: 500,
        color: L.body,
        lineHeight: 1.45,
        maxWidth: 3000,
      }}
    >
      Factories already collect the data they need to grow. The value — and
      the market — is in making it correlate: across formats, systems and
      departments.
    </div>
    <div style={{ flex: 1 }} />
    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
      <BySoundSafe size={80} />
    </div>
  </Slide>
);

/** I2 light — the problem / why now */
export const InvestorSlide2Light: React.FC = () => (
  <Slide>
    <Overline>The problem · Why now</Overline>
    <div style={{ display: 'flex', gap: 150, marginTop: 100, flex: 1 }}>
      <div style={{ flex: 1.1, display: 'flex', flexDirection: 'column', gap: 66 }}>
        <div
          style={{
            fontSize: 128,
            fontWeight: 800,
            color: L.text,
            letterSpacing: -2.5,
            lineHeight: 1.12,
          }}
        >
          Industry 4.0 runs on data. The data doesn't talk.
        </div>
        <div
          style={{
            fontSize: 62,
            fontWeight: 500,
            color: L.body,
            lineHeight: 1.48,
          }}
        >
          Enterprise systems — ERP orders, invoices, shipments, quality records
          — hold half the story. Smart machines and cameras produce the other
          half. Today they live in silos: ERP, MES, spreadsheets, PDFs, image
          and audio archives, telemetry historians.
        </div>
      </div>
      <div
        style={{
          flex: 1,
          borderRadius: 36,
          border: `3px solid ${L.border}`,
          background: L.cardBg,
          boxShadow: L.cardShadow,
          padding: '84px 90px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 54,
        }}
      >
        <div
          style={{
            fontSize: 50,
            fontWeight: 700,
            letterSpacing: 6,
            textTransform: 'uppercase',
            color: L.textSecondary,
          }}
        >
          Where growth waits
        </div>
        <Bullet size={54}>A +20% capacity call debated for weeks — the load data was streaming all along</Bullet>
        <Bullet size={54}>Material buys padded "just in case" — the forecast never met the floor</Bullet>
        <Bullet size={54}>New orders turned away while other lines ran under-loaded</Bullet>
        <Bullet size={54}>Four systems, four answers — expansion decided on gut feel</Bullet>
        <div
          style={{
            marginTop: 10,
            fontSize: 54,
            fontWeight: 700,
            color: L.text,
            lineHeight: 1.4,
          }}
        >
          The answers existed. They just never met.
        </div>
      </div>
    </div>
    <div
      style={{
        marginTop: 90,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <Lockup size={72} />
      <BySoundSafe size={64} />
    </div>
  </Slide>
);

/** I3 light — the solution / platform */
export const InvestorSlide3Light: React.FC = () => (
  <Slide>
    <Overline>The solution — OmniusGrid platform</Overline>
    <div style={{ display: 'flex', gap: 130, marginTop: 70, flex: 1 }}>
      <div
        style={{
          width: 1520,
          display: 'flex',
          flexDirection: 'column',
          gap: 44,
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            fontSize: 116,
            fontWeight: 800,
            color: L.text,
            letterSpacing: -2.5,
            lineHeight: 1.1,
          }}
        >
          One engine, four moats.
        </div>
        {(
          [
            [
              'Multimodal ingestion',
              'Spreadsheets, PDFs, photos, audio, video and live sensors — one queryable context, no schema work.',
              ['XLSX', 'PDF', 'JPG', 'WAV', '● LIVE'],
            ],
            [
              'Enterprise connectors',
              'Seven ERPs live — SAP, Oracle, NetSuite, Dynamics, Odoo, Infor, Epicor — plus MES, telemetry, GPS fleets.',
              ['SAP', 'Oracle', 'NetSuite', '+4 more'],
            ],
            [
              'Correlation AI',
              'Plain-language questions; answers show their reasoning and a score, with assignable actions.',
              ['GO / risk scores', 'Reasoning trace', '1-click actions'],
            ],
            [
              'End-to-end graph',
              'Shop floor → logistics → financials → customer — how the operation actually behaves.',
              ['OEE', 'Kanban', 'TMS', 'YMS', 'ERP'],
            ],
          ] as [string, string, string[]][]
        ).map(([h, b, chips]) => (
          <div key={h} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ fontSize: 60, fontWeight: 800, color: L.accentText }}>{h}</div>
            <div
              style={{
                fontSize: 46,
                fontWeight: 500,
                color: L.body,
                lineHeight: 1.4,
              }}
            >
              {b}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, marginTop: 6 }}>
              {chips.map((c) => (
                <MiniChip key={c} label={c} size={30} />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 36 }}>
        <CorrelationAnswerLight compact />
        <div
          style={{
            alignSelf: 'stretch',
            padding: '24px 44px',
            borderRadius: 24,
            border: `3px solid ${L.accentBorder}`,
            background: L.accentBg,
            color: L.accentText,
            fontSize: 44,
            fontWeight: 700,
            textAlign: 'center',
            whiteSpace: 'nowrap',
          }}
        >
          ⚡ One question de-risked the expansion — purchasing, shipping and the floor
        </div>
      </div>
    </div>
    <div
      style={{
        marginTop: 60,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <div style={{ fontSize: 56, fontWeight: 700, color: L.text }}>
        <Wordmark />{' '}
        <span style={{ color: L.textSecondary, fontWeight: 500 }}>
          · built and shipping today
        </span>
      </div>
      <BySoundSafe size={64} />
    </div>
  </Slide>
);
