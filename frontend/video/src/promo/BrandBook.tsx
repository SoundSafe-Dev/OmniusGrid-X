import React from 'react';
import { Img, staticFile } from 'remotion';
import { theme } from '../theme';
import { Wordmark } from '../components/Wordmark';
import { Base, BySoundSafe } from './PromoCards';

/**
 * OmniusGrid brand guidelines book — nine 16:9 pages (3840x2160), bound to
 * out/brand/OmniusGrid-Brand-Guidelines.pdf. The source of truth for the
 * copy is frontend/video/BRAND.md; keep the two in sync.
 */

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
const GREEN = '#4ade80';
const RED = '#f87171';

const Page: React.FC<{ children: React.ReactNode; pad?: string }> = ({
  children,
  pad = '130px 170px',
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

const PageHead: React.FC<{ no: string; title: string }> = ({ no, title }) => (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
    <div
      style={{
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
      {no} · {title}
    </div>
    <span style={{ fontSize: 46, color: theme.darkTextSecondary, fontWeight: 600 }}>
      <span style={{ color: theme.darkText }}>
        <Wordmark />
      </span>{' '}
      · Brand Guidelines
    </span>
  </div>
);

const Label: React.FC<{ children: React.ReactNode; color?: string }> = ({
  children,
  color = theme.darkTextSecondary,
}) => (
  <div
    style={{
      fontSize: 36,
      fontWeight: 800,
      letterSpacing: 6,
      textTransform: 'uppercase',
      color,
    }}
  >
    {children}
  </div>
);

const Card: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({
  children,
  style,
}) => (
  <div
    style={{
      borderRadius: 32,
      border: `3px solid ${theme.darkBorder}`,
      background: 'rgba(255,255,255,0.03)',
      padding: '56px 64px',
      display: 'flex',
      flexDirection: 'column',
      gap: 30,
      ...style,
    }}
  >
    {children}
  </div>
);

const Chip: React.FC<{ label: string; tone?: 'blue' | 'green' | 'neutral'; size?: number }> = ({
  label,
  tone = 'neutral',
  size = 36,
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

const DoDont: React.FC<{ good: string; bad: string }> = ({ good, bad }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    <div style={{ fontSize: 38, lineHeight: 1.35, color: 'rgba(250,250,250,0.9)' }}>
      <span style={{ color: GREEN, fontWeight: 800 }}>✓</span> {good}
    </div>
    <div style={{ fontSize: 38, lineHeight: 1.35, color: theme.darkTextSecondary }}>
      <span style={{ color: RED, fontWeight: 800 }}>✗</span> {bad}
    </div>
  </div>
);

// ---------------------------------------------------------------- 1 · cover

export const BrandPage1: React.FC = () => (
  <Page>
    <div style={{ flex: 1 }} />
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 80 }}>
      <div
        style={{
          width: 420,
          height: 420,
          borderRadius: 92,
          background: '#ffffff',
          boxShadow: '0 0 180px rgba(250,250,250,0.2), 0 50px 150px rgba(0,0,0,0.6)',
          overflow: 'hidden',
        }}
      >
        <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 420, height: 420 }} />
      </div>
      <div style={{ fontSize: 230, color: theme.darkText, letterSpacing: -5, lineHeight: 1 }}>
        <Wordmark />
      </div>
      <div style={{ height: 8, width: 560, borderRadius: 4, background: theme.highlight }} />
      <div style={{ fontSize: 96, fontWeight: 700, color: theme.darkText }}>
        Brand Guidelines
      </div>
      <div style={{ fontSize: 48, fontWeight: 600, color: theme.darkTextSecondary }}>
        v1.0 · July 2026 · the delegation-ready edition
      </div>
    </div>
    <div style={{ flex: 1 }} />
    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
      <BySoundSafe size={72} />
    </div>
  </Page>
);

// ------------------------------------------------------ 2 · brand narrative

export const BrandPage2: React.FC = () => (
  <Page>
    <PageHead no="01" title="Brand narrative" />
    <div style={{ display: 'flex', gap: 140, marginTop: 100, flex: 1 }}>
      <div style={{ flex: 1.15, display: 'flex', flexDirection: 'column', gap: 70 }}>
        <div
          style={{
            fontSize: 148,
            fontWeight: 800,
            color: theme.darkText,
            letterSpacing: -3,
            lineHeight: 1.1,
          }}
        >
          Enterprise data meets{' '}
          <span style={{ color: theme.highlight }}>machine data</span>.
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 26 }}>
          <Label>Positioning</Label>
          <div style={{ fontSize: 58, fontWeight: 500, color: 'rgba(250,250,250,0.9)', lineHeight: 1.45 }}>
            OmniusGrid is the correlation engine for Industry 4.0. It takes the
            files a factory already has — ERP orders, invoices, shipments,
            quality records — and the machine data it already streams, and
            makes them answer questions together.
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 26 }}>
          <Label>Elevator pitch — 30 seconds</Label>
          <div style={{ fontSize: 50, fontWeight: 500, color: 'rgba(250,250,250,0.82)', lineHeight: 1.48 }}>
            Factories already produce everything they need to know: enterprise
            records in ERP, spreadsheets and PDFs, and live telemetry from the
            floor. OmniusGrid ingests every format, streams machine data
            alongside, and answers plain-language questions with visible
            reasoning, a score and a one-click action. The gains come when the
            two halves meet — transparency, flexibility, better decisions.
          </div>
        </div>
      </div>
      <div style={{ flex: 0.85, display: 'flex', flexDirection: 'column', gap: 44, justifyContent: 'center' }}>
        <Card>
          <Label color={theme.highlightSoft}>The rule that never breaks</Label>
          <div style={{ fontSize: 54, fontWeight: 700, color: theme.darkText, lineHeight: 1.4 }}>
            Enterprise data first, machine data second — always in that order,
            always with examples.
          </div>
          <div style={{ fontSize: 42, color: theme.darkTextSecondary, lineHeight: 1.45 }}>
            "ERP orders, invoices, shipments, quality records" before "sensors
            and cameras" — in every asset, every pitch, every post.
          </div>
        </Card>
        <Card>
          <Label color={theme.highlightSoft}>Boilerplate — copy verbatim</Label>
          <div style={{ fontSize: 42, fontWeight: 500, color: 'rgba(250,250,250,0.88)', lineHeight: 1.5 }}>
            OmniusGrid, by SoundSafe.ai, correlates enterprise data — ERP
            orders, invoices, shipments, quality records — with live machine
            data from the factory floor. Teams drop in the files they already
            have, ask questions in plain language, and get answers that show
            their reasoning, carry a score, and ship with a one-click action —
            across OEE, Kanban, TMS, YMS and seven live ERP integrations.
          </div>
        </Card>
      </div>
    </div>
    <div style={{ marginTop: 80, display: 'flex', justifyContent: 'flex-end' }}>
      <BySoundSafe size={64} />
    </div>
  </Page>
);

// -------------------------------------------------- 3 · messaging architecture

export const BrandPage3: React.FC = () => (
  <Page>
    <PageHead no="02" title="Messaging architecture" />
    <div style={{ display: 'flex', gap: 130, marginTop: 90, flex: 1 }}>
      <div style={{ flex: 1.1, display: 'flex', flexDirection: 'column', gap: 52, justifyContent: 'center' }}>
        {(
          [
            ['Master tagline', 'Unleash the power of data correlation', 118],
            ['Category line', 'The correlation engine for Industry 4.0.', 76],
            ['Product line', 'Just ask. It correlates.', 76],
            ['Problem hook', "Industry 4.0 runs on data. The data doesn't talk.", 62],
            ['Payoff line', 'The answers existed. They just never met.', 62],
          ] as [string, string, number][]
        ).map(([label, line, size]) => (
          <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Label>{label}</Label>
            <div
              style={{
                fontSize: size,
                fontWeight: 800,
                color: label === 'Master tagline' ? theme.darkText : 'rgba(250,250,250,0.92)',
                letterSpacing: -1.5,
                lineHeight: 1.15,
              }}
            >
              {label === 'Master tagline' ? (
                <>
                  Unleash the power of{' '}
                  <span style={{ color: theme.highlight }}>data correlation</span>
                </>
              ) : (
                line
              )}
            </div>
          </div>
        ))}
      </div>
      <div style={{ flex: 0.9, display: 'flex', flexDirection: 'column', gap: 40, justifyContent: 'center' }}>
        <Card>
          <Label color={theme.highlightSoft}>Three pillars — fixed names, never reworded</Label>
          {(
            [
              ['Optimized Operations', 'ingested files × live telemetry, OEE, headroom'],
              ['Actionable Insights', 'GO / risk scores, action approval, Kanban dispatch'],
              ['Maximum Efficiency', 'TMS, YMS, detention alerts, OTIF'],
            ] as [string, string][]
          ).map(([h, b]) => (
            <div key={h} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ fontSize: 52, fontWeight: 800, color: theme.darkText }}>{h}.</div>
              <div style={{ fontSize: 40, color: theme.darkTextSecondary }}>{b}</div>
            </div>
          ))}
        </Card>
        <Card>
          <Label color={theme.highlightSoft}>Canonical example — use everywhere</Label>
          <div style={{ fontSize: 44, fontWeight: 600, color: 'rgba(250,250,250,0.92)', lineHeight: 1.45 }}>
            "What happens if we raise Line 3 output by 20%?"
          </div>
          <div style={{ fontSize: 38, color: theme.darkTextSecondary, lineHeight: 1.5 }}>
            <span style={{ fontFamily: MONO, color: theme.darkText }}>material-forecast_q3.xlsx</span>{' '}
            ×{' '}
            <span style={{ fontFamily: MONO, color: theme.darkText }}>carrier-agreement_2026.pdf</span>{' '}
            × <span style={{ fontFamily: MONO, color: theme.darkText }}>Lines 1–3 stream</span> →{' '}
            <span style={{ color: GREEN, fontWeight: 800 }}>GO · 91</span> → green-light,
            material orders dispatched. Growth-positive scenarios lead; risk
            examples support.
          </div>
        </Card>
      </div>
    </div>
    <div style={{ marginTop: 70, display: 'flex', justifyContent: 'flex-end' }}>
      <BySoundSafe size={64} />
    </div>
  </Page>
);

// ---------------------------------------------------------- 4 · voice & tone

export const BrandPage4: React.FC = () => (
  <Page>
    <PageHead no="03" title="Voice & tone" />
    <div
      style={{
        marginTop: 90,
        flex: 1,
        display: 'grid',
        gridTemplateColumns: '1fr 1fr 1fr',
        gridTemplateRows: '1fr 1fr',
        gap: 56,
      }}
    >
      {(
        [
          [
            'Concrete over abstract',
            'Name the file, the line, the number.',
            '"Line 3 at 63% load — green-light +20%."',
            '"AI-driven insights optimize productivity."',
          ],
          [
            'Short declaratives',
            'One idea per sentence. The em-dash makes the turn.',
            '"Capacity found, not bought."',
            'Forty-word feature sentences with three commas.',
          ],
          [
            'Growth-positive',
            'Lead with what teams green-light; leaks are evidence.',
            '"Commit to more volume knowing OTIF holds."',
            'Fear-first pitches about downtime and fines.',
          ],
          [
            'Show the product',
            'Every capability claim is a real pane, button or chip.',
            'GO · 91 badge, the load bar, a dispatched Kanban task.',
            'Stock photos, abstract 3D cubes, robot handshakes.',
          ],
          [
            'No AI mysticism',
            'The reasoning is always shown — say so.',
            '"Every answer shows its reasoning."',
            '"Magic black-box intelligence at enterprise scale."',
          ],
          [
            'Enterprise data first',
            'ERP orders, invoices, shipments, quality records — then machines.',
            'That order, with those examples.',
            'Leading with sensors and cameras.',
          ],
        ] as [string, string, string, string][]
      ).map(([h, sub, good, bad], i) => (
        <Card key={h} style={{ gap: 24, padding: '48px 56px', justifyContent: 'center' }}>
          <div style={{ fontSize: 56, fontWeight: 800, color: theme.highlightSoft }}>
            {i + 1}. {h}
          </div>
          <div style={{ fontSize: 40, fontWeight: 600, color: theme.darkText, lineHeight: 1.35 }}>
            {sub}
          </div>
          <DoDont good={good} bad={bad} />
        </Card>
      ))}
    </div>
    <div style={{ marginTop: 70, display: 'flex', justifyContent: 'flex-end' }}>
      <BySoundSafe size={64} />
    </div>
  </Page>
);

// ------------------------------------------------------ 5 · logo & wordmark

export const BrandPage5: React.FC = () => (
  <Page>
    <PageHead no="04" title="Logo & wordmark" />
    <div style={{ display: 'flex', gap: 130, marginTop: 90, flex: 1 }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 44 }}>
        <Card style={{ alignItems: 'center', padding: '90px 64px', gap: 60 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 56 }}>
            <div
              style={{
                width: 220,
                height: 220,
                borderRadius: 48,
                background: '#ffffff',
                overflow: 'hidden',
              }}
            >
              <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 220, height: 220 }} />
            </div>
            <span style={{ fontSize: 160, color: theme.darkText, letterSpacing: -3 }}>
              <Wordmark />
            </span>
          </div>
          <div style={{ fontSize: 38, color: theme.darkTextSecondary }}>
            Primary lockup on charcoal — the mark always sits on its white tile
          </div>
        </Card>
        <div
          style={{
            borderRadius: 32,
            background: '#f7f7f8',
            border: `3px solid ${theme.darkBorder}`,
            padding: '70px 64px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 40,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 40 }}>
            <div
              style={{
                width: 140,
                height: 140,
                borderRadius: 32,
                background: '#ffffff',
                border: '3px solid #e2e2e6',
                overflow: 'hidden',
              }}
            >
              <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 140, height: 140 }} />
            </div>
            <span style={{ fontSize: 110, color: '#141414', letterSpacing: -2 }}>
              <Wordmark />
            </span>
          </div>
          <div style={{ fontSize: 36, color: '#5c5c62' }}>
            Light contexts — add the hairline border to the tile
          </div>
        </div>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 40, justifyContent: 'center' }}>
        {(
          [
            [
              'Split weight, always',
              <>
                <b style={{ color: theme.darkText }}>Omnius</b> at weight 800,{' '}
                <span style={{ color: theme.darkText }}>Grid</span> at 400 — one color. Never
                all-bold, never two colors, never "OMNIUSGRID" in running copy.
              </>,
            ],
            [
              'The white tile',
              <>
                The gear never touches charcoal directly. It lives on a white
                rounded tile — hairline border on light backgrounds.
              </>,
            ],
            [
              'SoundSafe attribution',
              <>
                Every outward asset carries{' '}
                <span style={{ color: theme.darkText, fontWeight: 700 }}>by + SoundSafe pill</span>,
                bottom-right. The SoundSafe logotype is dark — it always sits on
                a white pill.
              </>,
            ],
            [
              'Clearspace & minimums',
              <>
                Clearspace: half the tile height on all sides. Minimum tile
                height 32 px on screen, 10 mm in print.
              </>,
            ],
            [
              "Don'ts",
              <>
                No recoloring, no stretching, no drop shadows on the wordmark,
                no placing the dark SoundSafe logotype on dark ground.
              </>,
            ],
          ] as [string, React.ReactNode][]
        ).map(([h, b]) => (
          <div key={h} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ fontSize: 52, fontWeight: 800, color: theme.highlightSoft }}>{h}</div>
            <div style={{ fontSize: 42, color: 'rgba(250,250,250,0.85)', lineHeight: 1.45 }}>{b}</div>
          </div>
        ))}
      </div>
    </div>
    <div style={{ marginTop: 70, display: 'flex', justifyContent: 'flex-end' }}>
      <BySoundSafe size={64} />
    </div>
  </Page>
);

// ------------------------------------------------------------------ 6 · color

const Swatch: React.FC<{ hex: string; name: string; dark?: boolean; border?: boolean }> = ({
  hex,
  name,
  dark,
  border,
}) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 14, width: 320 }}>
    <div
      style={{
        height: 170,
        borderRadius: 24,
        background: hex,
        border: border ? `3px solid ${theme.darkBorder}` : '3px solid transparent',
      }}
    />
    <div style={{ fontSize: 36, fontWeight: 700, color: theme.darkText }}>{name}</div>
    <div style={{ fontFamily: MONO, fontSize: 32, color: theme.darkTextSecondary }}>{hex}</div>
  </div>
);

export const BrandPage6: React.FC = () => (
  <Page>
    <PageHead no="05" title="Color" />
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 90,
        marginTop: 90,
        flex: 1,
        justifyContent: 'center',
      }}
    >
      <div style={{ display: 'flex', gap: 120 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 34 }}>
          <Label>Dark — the default</Label>
          <div style={{ display: 'flex', gap: 40 }}>
            <Swatch hex="#0a0a0a" name="Background" border />
            <Swatch hex="#171717" name="Panel" border />
            <Swatch hex="#2e2e2e" name="Border" />
            <Swatch hex="#fafafa" name="Text" />
            <Swatch hex="#a3a3a3" name="Secondary" />
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 34 }}>
          <Label>Light — print & email</Label>
          <div style={{ display: 'flex', gap: 40 }}>
            <Swatch hex="#f7f7f8" name="Background" />
            <Swatch hex="#ffffff" name="Card" />
            <Swatch hex="#141414" name="Text" border />
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 120, alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 34 }}>
          <Label>Accents — semantic, never decorative</Label>
          <div style={{ display: 'flex', gap: 40 }}>
            <Swatch hex="#3b82f6" name="Brand blue" />
            <Swatch hex="#93c5fd" name="Blue soft (dark)" />
            <Swatch hex="#2563eb" name="Blue deep (light)" />
            <Swatch hex="#4ade80" name="Live / GO" />
            <Swatch hex="#ef4444" name="Risk only" />
          </div>
        </div>
        <Card style={{ flex: 1, justifyContent: 'center', gap: 34, alignSelf: 'stretch' }}>
          <Label color={theme.highlightSoft}>The accent law</Label>
          <div style={{ fontSize: 54, fontWeight: 700, color: theme.darkText, lineHeight: 1.4 }}>
            One blue accent. If a layout needs a second accent color, the
            layout is wrong.
          </div>
          <div style={{ fontSize: 42, color: theme.darkTextSecondary, lineHeight: 1.5 }}>
            Blue marks the brand: highlights, primary buttons, file chips.
            Green is reserved for live streams and GO scores. Red is reserved
            for risk. Neither is ever decoration.
          </div>
        </Card>
      </div>
    </div>
    <div style={{ marginTop: 70, display: 'flex', justifyContent: 'flex-end' }}>
      <BySoundSafe size={64} />
    </div>
  </Page>
);

// ------------------------------------------- 7 · typography & data language

export const BrandPage7: React.FC = () => (
  <Page>
    <PageHead no="06" title="Typography & data language" />
    <div style={{ display: 'flex', gap: 130, marginTop: 90, flex: 1 }}>
      <div style={{ flex: 1.1, display: 'flex', flexDirection: 'column', gap: 54, justifyContent: 'center' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <Label>Typeface — the system stack</Label>
          <div style={{ fontSize: 44, color: 'rgba(250,250,250,0.85)', lineHeight: 1.45 }}>
            -apple-system · Segoe UI · Roboto · Helvetica Neue — native, fast,
            everywhere. No licensed display faces.
          </div>
        </div>
        {(
          [
            ['Display · 800 · −3 tracking', 148, 800, 'Just ask.'],
            ['Headline · 800 · −2.5', 96, 800, 'One engine, four moats.'],
            ['Body · 500 · 1.45 line height', 54, 500, 'Enterprise data holds half the story.'],
          ] as [string, number, number, string][]
        ).map(([label, size, weight, sample]) => (
          <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <Label>{label}</Label>
            <div
              style={{
                fontSize: size,
                fontWeight: weight,
                color: theme.darkText,
                letterSpacing: size > 90 ? -2.5 : 0,
                lineHeight: 1.15,
              }}
            >
              {sample}
            </div>
          </div>
        ))}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Label>Overline · 700 · +8 tracking · uppercase</Label>
          <div
            style={{
              fontSize: 42,
              fontWeight: 700,
              letterSpacing: 8,
              textTransform: 'uppercase',
              color: theme.darkTextSecondary,
            }}
          >
            What OmniusGrid does
          </div>
        </div>
      </div>
      <div style={{ flex: 0.9, display: 'flex', flexDirection: 'column', gap: 44, justifyContent: 'center' }}>
        <Card>
          <Label color={theme.highlightSoft}>Data speaks monospace</Label>
          <div style={{ fontSize: 42, color: 'rgba(250,250,250,0.85)', lineHeight: 1.5 }}>
            Every data artifact — file names, IDs, line names — is set in{' '}
            <span style={{ fontFamily: MONO, fontWeight: 700, color: theme.darkText }}>
              ui-monospace
            </span>
            :
          </div>
          <div style={{ fontFamily: MONO, fontSize: 44, fontWeight: 700, color: theme.darkText, lineHeight: 1.6 }}>
            material-forecast_q3.xlsx
            <br />
            SHP-2214 · WO-4482 · Line 3
          </div>
        </Card>
        <Card>
          <Label color={theme.highlightSoft}>The chip system</Label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 30 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
              <Chip label="XLSX" tone="blue" />
              <Chip label="PDF" tone="blue" />
              <Chip label="JPG" tone="blue" />
              <Chip label="WAV" tone="blue" />
              <span style={{ fontSize: 38, color: theme.darkTextSecondary }}>
                blue — ingested file formats
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
              <Chip label="● LIVE" tone="green" />
              <Chip label="GO · 91" tone="green" />
              <span style={{ fontSize: 38, color: theme.darkTextSecondary }}>
                green — live streams & GO scores
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
              <Chip label="OEE" />
              <Chip label="Kanban" />
              <Chip label="TMS" />
              <Chip label="YMS" />
              <Chip label="ERP" />
              <span style={{ fontSize: 38, color: theme.darkTextSecondary }}>
                neutral — product modules
              </span>
            </div>
          </div>
        </Card>
      </div>
    </div>
    <div style={{ marginTop: 70, display: 'flex', justifyContent: 'flex-end' }}>
      <BySoundSafe size={64} />
    </div>
  </Page>
);

// -------------------------------------------------------------- 8 · UI motifs

export const BrandPage8: React.FC = () => (
  <Page>
    <PageHead no="07" title="Signature motifs" />
    <div
      style={{
        marginTop: 90,
        flex: 1,
        display: 'grid',
        gridTemplateColumns: '1fr 1fr 1fr',
        gridTemplateRows: '1fr 1fr',
        gap: 56,
      }}
    >
      <Card style={{ gap: 26 }}>
        <div
          style={{
            flex: 1,
            borderRadius: 20,
            border: `3px solid ${theme.darkBorder}`,
            backgroundImage: `linear-gradient(${theme.darkBorder} 1px, transparent 1px), linear-gradient(90deg, ${theme.darkBorder} 1px, transparent 1px)`,
            backgroundSize: '60px 60px',
            maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 85%)',
            WebkitMaskImage: 'radial-gradient(ellipse at center, black 30%, transparent 85%)',
            minHeight: 220,
          }}
        />
        <div style={{ fontSize: 46, fontWeight: 800, color: theme.darkText }}>The grid texture</div>
        <div style={{ fontSize: 36, color: theme.darkTextSecondary, lineHeight: 1.45 }}>
          120 px grid at ~20% opacity, radially masked. Texture — never loud
          enough to read as a pattern.
        </div>
      </Card>
      <Card style={{ gap: 26 }}>
        <div
          style={{
            borderRadius: 20,
            border: `3px solid rgba(255,255,255,0.10)`,
            background: 'linear-gradient(180deg, #15151b 0%, #0d0d11 100%)',
            overflow: 'hidden',
            minHeight: 220,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '20px 30px',
              borderBottom: '3px solid rgba(255,255,255,0.10)',
              background: 'rgba(255,255,255,0.025)',
            }}
          >
            {[0, 1, 2].map((i) => (
              <div key={i} style={{ width: 14, height: 14, borderRadius: 7, background: 'rgba(255,255,255,0.18)' }} />
            ))}
            <span style={{ marginLeft: 12, fontSize: 28, fontWeight: 600, color: theme.darkTextSecondary }}>
              Correlation AI — analysis session
            </span>
          </div>
          <div style={{ flex: 1 }} />
        </div>
        <div style={{ fontSize: 46, fontWeight: 800, color: theme.darkText }}>The product window</div>
        <div style={{ fontSize: 36, color: theme.darkTextSecondary, lineHeight: 1.45 }}>
          Three dots + session title + context chip. Product UI is always
          framed as a window — never a floating screenshot.
        </div>
      </Card>
      <Card style={{ gap: 26 }}>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', minHeight: 220 }}>
          <div
            style={{
              background: '#ffffff',
              color: theme.darkBg,
              borderRadius: '24px 24px 6px 24px',
              padding: '22px 38px',
              fontSize: 40,
              fontWeight: 600,
            }}
          >
            What happens if we raise Line 3 output by 20%?
          </div>
        </div>
        <div style={{ fontSize: 46, fontWeight: 800, color: theme.darkText }}>The question bubble</div>
        <div style={{ fontSize: 36, color: theme.darkTextSecondary, lineHeight: 1.45 }}>
          Right-aligned, one line where possible. Inverts with the theme —
          white on dark, near-black on light.
        </div>
      </Card>
      <Card style={{ gap: 26 }}>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 24, minHeight: 220 }}>
          <span
            style={{
              fontSize: 40,
              fontWeight: 800,
              color: GREEN,
              border: '3px solid rgba(74,222,128,0.55)',
              background: 'rgba(74,222,128,0.14)',
              borderRadius: 14,
              padding: '12px 30px',
            }}
          >
            GO · 91
          </span>
          <span
            style={{
              fontSize: 40,
              fontWeight: 800,
              color: '#fca5a5',
              border: '3px solid rgba(239,68,68,0.55)',
              background: 'rgba(239,68,68,0.16)',
              borderRadius: 14,
              padding: '12px 30px',
            }}
          >
            RISK 78
          </span>
        </div>
        <div style={{ fontSize: 46, fontWeight: 800, color: theme.darkText }}>Score badges</div>
        <div style={{ fontSize: 36, color: theme.darkTextSecondary, lineHeight: 1.45 }}>
          Every answer carries one. GO leads in marketing; RISK appears as
          supporting evidence.
        </div>
      </Card>
      <Card style={{ gap: 26 }}>
        <div
          style={{
            flex: 1,
            borderLeft: `8px solid ${theme.highlight}`,
            background: 'rgba(59,130,246,0.08)',
            borderRadius: 16,
            padding: '28px 34px',
            display: 'flex',
            flexDirection: 'column',
            gap: 14,
            justifyContent: 'center',
            minHeight: 220,
          }}
        >
          <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: 4, textTransform: 'uppercase', color: theme.highlightSoft }}>
            The power-up
          </div>
          <div style={{ fontSize: 36, color: 'rgba(250,250,250,0.92)', lineHeight: 1.4 }}>
            63% load streaming → +20% green-lit. Capacity found, not bought.
          </div>
        </div>
        <div style={{ fontSize: 46, fontWeight: 800, color: theme.darkText }}>The power-up inset</div>
        <div style={{ fontSize: 36, color: theme.darkTextSecondary, lineHeight: 1.45 }}>
          Blue left bar + label + a real UI artifact + one-line payoff. This is
          how benefits are proven.
        </div>
      </Card>
      <Card style={{ gap: 26 }}>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', minHeight: 220 }}>
          <div
            style={{
              width: '100%',
              padding: '22px 36px',
              borderRadius: 20,
              border: '3px solid rgba(59,130,246,0.55)',
              background: 'rgba(59,130,246,0.10)',
              color: theme.highlightSoft,
              fontSize: 36,
              fontWeight: 700,
              textAlign: 'center',
            }}
          >
            ⚡ One question de-risked the expansion
          </div>
        </div>
        <div style={{ fontSize: 46, fontWeight: 800, color: theme.darkText }}>The payoff strip</div>
        <div style={{ fontSize: 36, color: theme.darkTextSecondary, lineHeight: 1.45 }}>
          ⚡ + one sentence, blue-tinted bar. Closes a story or a slide —
          maximum one per asset.
        </div>
      </Card>
    </div>
    <div style={{ marginTop: 70, display: 'flex', justifyContent: 'flex-end' }}>
      <BySoundSafe size={64} />
    </div>
  </Page>
);

// ------------------------------------------------- 9 · applications & sign-off

export const BrandPage9: React.FC = () => (
  <Page>
    <PageHead no="08" title="Applications & sign-off" />
    <div style={{ display: 'flex', gap: 130, marginTop: 90, flex: 1 }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 44, justifyContent: 'center' }}>
        <Card>
          <Label color={theme.highlightSoft}>The asset library — all code, all re-renderable</Label>
          {(
            [
              ['Product demo film', '4K 16:9 + mobile 9:16 · 104 s · with score'],
              ['Instagram cards ×3', 'logo · tagline · Industry 4.0 explainer (1080×1350)'],
              ['Client deck ×3 slides', 'dark + light · PNG + bound PDF'],
              ['Investor deck ×3 slides', 'dark + light · PNG + bound PDF'],
              ['Wordmark PNG', 'white on black · 3840×1400'],
              ['This brand book', 'nine pages · bound PDF'],
            ] as [string, string][]
          ).map(([h, b]) => (
            <div key={h} style={{ display: 'flex', alignItems: 'baseline', gap: 24 }}>
              <div style={{ fontSize: 44, fontWeight: 700, color: theme.darkText, whiteSpace: 'nowrap' }}>{h}</div>
              <div style={{ fontSize: 36, color: theme.darkTextSecondary }}>{b}</div>
            </div>
          ))}
          <div style={{ fontSize: 38, color: 'rgba(250,250,250,0.85)', lineHeight: 1.5, marginTop: 10 }}>
            Every asset is generated from code in{' '}
            <span style={{ fontFamily: MONO, color: theme.darkText }}>frontend/video</span>.
            Request changes, not redraws — any slide re-renders in minutes,
            and dark/light stay in sync.
          </div>
        </Card>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 44, justifyContent: 'center' }}>
        <Card>
          <Label color={theme.highlightSoft}>Sign-off checklist — every asset, before it ships</Label>
          {[
            'Split-weight wordmark — Omnius 800 / Grid 400',
            'One blue accent; green only for live & GO; red only for risk',
            'Enterprise data named before machine data',
            'Canonical Line 3 example (or an approved successor)',
            'Real product UI for every capability claim',
            '"by SoundSafe" pill, bottom-right',
            'Dark + light variants where the channel needs both',
            'No "app.omniusgrid.io" URLs until launch',
          ].map((item) => (
            <div key={item} style={{ display: 'flex', alignItems: 'flex-start', gap: 24 }}>
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: 10,
                  border: `3px solid ${theme.highlightSoft}`,
                  marginTop: 6,
                  flexShrink: 0,
                }}
              />
              <div style={{ fontSize: 42, color: 'rgba(250,250,250,0.9)', lineHeight: 1.4 }}>{item}</div>
            </div>
          ))}
        </Card>
        <div style={{ fontSize: 40, color: theme.darkTextSecondary }}>
          Brand owner & final sign-off:{' '}
          <span style={{ fontFamily: MONO, color: theme.darkText }}>hamad@soundsafe.ai</span>
        </div>
      </div>
    </div>
    <div style={{ marginTop: 70, display: 'flex', justifyContent: 'flex-end' }}>
      <BySoundSafe size={64} />
    </div>
  </Page>
);
