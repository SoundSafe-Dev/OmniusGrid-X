import React from 'react';
import { Img, staticFile } from 'remotion';
import { theme } from '../theme';
import { Wordmark } from '../components/Wordmark';
import { Base, BySoundSafe } from './PromoCards';

/**
 * Two 3-slide 16:9 decks (rendered 3840x2160, delivered at 1920x1080):
 * a client-oriented story (problem → what it does → outcomes) and an
 * investor-oriented story (thesis → problem/market → platform).
 * Light-theme duplicates live in DeckCardsLight.tsx — keep copy in sync.
 */

const Overline: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      alignSelf: 'flex-start',
      padding: '18px 48px',
      borderRadius: 999,
      border: `3px solid ${theme.darkBorder}`,
      color: theme.darkTextSecondary,
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
        overflow: 'hidden',
        flexShrink: 0,
      }}
    >
      <Img
        src={staticFile('omniusgrid-logo.png')}
        style={{ width: size * 1.2, height: size * 1.2 }}
      />
    </div>
    <span style={{ fontSize: size, color: theme.darkText, letterSpacing: -2 }}>
      <Wordmark />
    </span>
  </div>
);

const Slide: React.FC<{ children: React.ReactNode; pad?: string }> = ({
  children,
  pad = '140px 170px',
}) => (
  <Base>
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
  </Base>
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
        boxShadow: '0 0 22px rgba(59,130,246,0.6)',
      }}
    />
    <div
      style={{
        fontSize: size,
        fontWeight: 500,
        color: 'rgba(250,250,250,0.9)',
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
      color: theme.darkTextSecondary,
    }}
  >
    {children}
  </div>
);

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

const chipTone = (c: string) => {
  if (c.startsWith('●') || c.startsWith('GO'))
    return { border: 'rgba(74,222,128,0.5)', bg: 'rgba(74,222,128,0.08)', color: '#4ade80' };
  if (['XLSX', 'PDF', 'JPG', 'WAV'].includes(c))
    return { border: 'rgba(59,130,246,0.45)', bg: 'rgba(59,130,246,0.08)', color: theme.highlightSoft };
  return { border: theme.darkBorder, bg: 'transparent', color: theme.darkTextSecondary };
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
        fontWeight: t.color === theme.darkTextSecondary ? 600 : 700,
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

/**
 * Product-style visual of one Correlation AI answer: the question, the
 * correlated-signal reasoning, the scored conclusion and the dispatched
 * actions. Shared by both decks.
 */
export const CorrelationAnswer: React.FC<{ compact?: boolean }> = ({ compact }) => (
  <div
    style={{
      flex: 1,
      borderRadius: 36,
      border: '3px solid rgba(255,255,255,0.10)',
      background: 'linear-gradient(180deg, #15151b 0%, #0d0d11 100%)',
      boxShadow:
        '0 0 140px rgba(59,130,246,0.14), 0 60px 160px rgba(0,0,0,0.55)',
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
        borderBottom: '3px solid rgba(255,255,255,0.10)',
        background: 'rgba(255,255,255,0.025)',
      }}
    >
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            width: 20,
            height: 20,
            borderRadius: 10,
            background: 'rgba(255,255,255,0.18)',
          }}
        />
      ))}
      <span
        style={{
          marginLeft: 22,
          fontSize: 38,
          fontWeight: 600,
          color: theme.darkTextSecondary,
        }}
      >
        Correlation AI — analysis session
      </span>
      <span
        style={{
          marginLeft: 'auto',
          fontSize: 32,
          fontWeight: 700,
          color: theme.highlightSoft,
          border: `3px solid rgba(59,130,246,0.45)`,
          background: 'rgba(59,130,246,0.10)',
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
          background: '#ffffff',
          color: theme.darkBg,
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
                  color: live ? '#4ade80' : theme.highlightSoft,
                  border: `3px solid ${
                    live ? 'rgba(74,222,128,0.5)' : 'rgba(59,130,246,0.45)'
                  }`,
                  background: live
                    ? 'rgba(74,222,128,0.10)'
                    : 'rgba(59,130,246,0.10)',
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
                  color: 'rgba(250,250,250,0.88)',
                }}
              >
                <span
                  style={{
                    fontFamily: MONO,
                    fontSize: 40,
                    fontWeight: 700,
                    color: theme.darkText,
                  }}
                >
                  {file}
                </span>{' '}
                <span style={{ color: theme.darkTextSecondary }}>({dept})</span>{' '}
                — {text}
              </div>
            </div>
            {i < SIGNALS.length - 1 && (
              <div
                style={{
                  height: 30,
                  marginLeft: 95,
                  borderLeft: '4px dashed rgba(59,130,246,0.45)',
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
          border: '3px solid rgba(74,222,128,0.4)',
          background: 'rgba(74,222,128,0.06)',
          borderRadius: 26,
          padding: '34px 44px',
        }}
      >
        <div
          style={{
            fontSize: 38,
            fontWeight: 800,
            color: '#4ade80',
            border: '3px solid rgba(74,222,128,0.55)',
            background: 'rgba(74,222,128,0.14)',
            borderRadius: 14,
            padding: '10px 26px',
            whiteSpace: 'nowrap',
            flexShrink: 0,
          }}
        >
          GO · 91
        </div>
        <div style={{ fontSize: 47, lineHeight: 1.36, color: 'rgba(250,250,250,0.94)' }}>
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
            color: '#0a0a0a',
            background: theme.highlightSoft,
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
            color: 'rgba(250,250,250,0.9)',
            border: `3px solid ${theme.darkBorder}`,
            borderRadius: 999,
            padding: '18px 42px',
          }}
        >
          Material orders → Purchasing <span style={{ color: '#4ade80' }}>✓ dispatched</span>
        </span>
        {!compact && (
          <span
            style={{
              fontSize: 42,
              fontWeight: 600,
              color: theme.darkTextSecondary,
              border: `3px solid ${theme.darkBorder}`,
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

/** C1 — the problem, in the brand's own words */
export const ClientSlide1: React.FC = () => (
  <Slide>
    <Lockup size={84} />
    <div style={{ flex: 1 }} />
    <div
      style={{
        fontSize: 170,
        fontWeight: 800,
        color: theme.darkText,
        letterSpacing: -3,
        lineHeight: 1.12,
      }}
    >
      You cannot make smart decisions with{' '}
      <span
        style={{
          background: '#ffffff',
          color: theme.darkBg,
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
        color: 'rgba(250,250,250,0.82)',
        lineHeight: 1.45,
        maxWidth: 3100,
      }}
    >
      Your operation already produces everything you need to know — in ERP
      orders, shipping logs, quality spreadsheets, service PDFs, camera feeds
      and machine telemetry.
      <br />
      <span style={{ whiteSpace: 'nowrap', color: theme.darkText, fontWeight: 600 }}>
        It just never ends up in the same place.
      </span>
    </div>
    <div style={{ flex: 1 }} />
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
      <BySoundSafe size={72} />
    </div>
  </Slide>
);

/** C2 — what it does: ask about growth, watch it correlate */
export const ClientSlide2: React.FC = () => (
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
            color: theme.darkText,
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
      <CorrelationAnswer />
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

/** C3 — outcomes + CTA */
export const ClientSlide3: React.FC = () => (
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
                    color: theme.darkText,
                  }}
                >
                  Line 3
                </span>
                <span
                  style={{
                    marginLeft: 'auto',
                    fontSize: 36,
                    fontWeight: 800,
                    color: theme.darkText,
                  }}
                >
                  63%{' '}
                  <span style={{ color: theme.darkTextSecondary, fontWeight: 500 }}>load</span>
                </span>
              </div>
              <div
                style={{
                  position: 'relative',
                  height: 22,
                  borderRadius: 11,
                  background: 'rgba(255,255,255,0.10)',
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
                    border: '3px dashed rgba(74,222,128,0.7)',
                    background: 'rgba(74,222,128,0.12)',
                  }}
                />
              </div>
              <div style={{ alignSelf: 'flex-end', fontSize: 30, fontWeight: 700, color: '#4ade80' }}>
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
                    color: '#0a0a0a',
                    background: theme.highlightSoft,
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
                  color: 'rgba(250,250,250,0.9)',
                  border: `3px solid ${theme.darkBorder}`,
                  borderRadius: 999,
                  padding: '12px 28px',
                }}
              >
                Kanban task → Purchasing <span style={{ color: '#4ade80' }}>✓ dispatched</span>
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
                    border: `3px solid ${theme.darkBorder}`,
                    borderRadius: 16,
                    padding: '14px 24px',
                  }}
                >
                  <span
                    style={{
                      fontSize: 26,
                      fontWeight: 800,
                      letterSpacing: 2,
                      color: theme.highlightSoft,
                    }}
                  >
                    {sys}
                  </span>
                  <span
                    style={{
                      fontFamily: MONO,
                      fontSize: 30,
                      fontWeight: 700,
                      color: theme.darkText,
                    }}
                  >
                    {id}
                  </span>
                  <span style={{ fontSize: 28, color: theme.darkTextSecondary }}>{mid}</span>
                  <span style={{ marginLeft: 'auto', fontSize: 28, fontWeight: 700, color: '#4ade80' }}>
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
            border: `3px solid ${theme.darkBorder}`,
            background: 'rgba(255,255,255,0.03)',
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
              color: theme.darkText,
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
              color: 'rgba(250,250,250,0.82)',
              lineHeight: 1.45,
            }}
          >
            {b}
          </div>
          <div
            style={{
              borderLeft: `8px solid ${theme.highlight}`,
              background: 'rgba(59,130,246,0.08)',
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
                color: theme.highlightSoft,
              }}
            >
              The power-up
            </div>
            {ui}
            <div
              style={{
                fontSize: 40,
                fontWeight: 500,
                color: 'rgba(250,250,250,0.92)',
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
          border: `3px solid rgba(59,130,246,0.55)`,
          background: 'rgba(59,130,246,0.10)',
          color: theme.highlightSoft,
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

/** I1 — thesis title slide */
export const InvestorSlide1: React.FC = () => (
  <Slide>
    <div style={{ flex: 1 }} />
    <div style={{ display: 'flex', alignItems: 'center', gap: 70 }}>
      <div
        style={{
          width: 300,
          height: 300,
          borderRadius: 66,
          background: '#ffffff',
          overflow: 'hidden',
          boxShadow: '0 0 160px rgba(250,250,250,0.2), 0 50px 140px rgba(0,0,0,0.6)',
          flexShrink: 0,
        }}
      >
        <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 300, height: 300 }} />
      </div>
      <div style={{ fontSize: 220, color: theme.darkText, letterSpacing: -5, lineHeight: 1 }}>
        <Wordmark />
      </div>
    </div>
    <div
      style={{
        marginTop: 90,
        fontSize: 96,
        fontWeight: 700,
        color: theme.darkText,
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
        color: 'rgba(250,250,250,0.78)',
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

/** I2 — the problem / why now */
export const InvestorSlide2: React.FC = () => (
  <Slide>
    <Overline>The problem · Why now</Overline>
    <div style={{ display: 'flex', gap: 150, marginTop: 100, flex: 1 }}>
      <div style={{ flex: 1.1, display: 'flex', flexDirection: 'column', gap: 66 }}>
        <div
          style={{
            fontSize: 128,
            fontWeight: 800,
            color: theme.darkText,
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
            color: 'rgba(250,250,250,0.82)',
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
          border: `3px solid ${theme.darkBorder}`,
          background: 'rgba(255,255,255,0.03)',
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
            color: theme.darkTextSecondary,
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
            color: theme.darkText,
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

/** I3 — the solution / platform */
export const InvestorSlide3: React.FC = () => (
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
            color: theme.darkText,
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
            <div style={{ fontSize: 60, fontWeight: 800, color: theme.highlightSoft }}>{h}</div>
            <div
              style={{
                fontSize: 46,
                fontWeight: 500,
                color: 'rgba(250,250,250,0.85)',
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
        <CorrelationAnswer compact />
        <div
          style={{
            alignSelf: 'stretch',
            padding: '24px 44px',
            borderRadius: 24,
            border: `3px solid rgba(59,130,246,0.55)`,
            background: 'rgba(59,130,246,0.10)',
            color: theme.highlightSoft,
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
      <div style={{ fontSize: 56, fontWeight: 700, color: theme.darkText }}>
        <Wordmark />{' '}
        <span style={{ color: theme.darkTextSecondary, fontWeight: 500 }}>
          · built and shipping today
        </span>
      </div>
      <BySoundSafe size={64} />
    </div>
  </Slide>
);
