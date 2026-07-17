import React from 'react';
import { AbsoluteFill, Img, staticFile } from 'remotion';
import { theme } from '../theme';
import { Wordmark } from '../components/Wordmark';

/**
 * Instagram 4:5 promo cards (rendered 2160x2700, delivered at 1080x1350).
 * Brand language: charcoal + faint grid texture, split-weight wordmark,
 * single blue accent.
 */

export const Backdrop: React.FC = () => (
  <AbsoluteFill
    style={{
      backgroundImage: `linear-gradient(${theme.darkBorder} 1px, transparent 1px), linear-gradient(90deg, ${theme.darkBorder} 1px, transparent 1px)`,
      backgroundSize: '120px 120px',
      opacity: 0.22,
      maskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
      WebkitMaskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
    }}
  />
);

export const Base: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill
    style={{
      background: theme.darkBg,
      fontFamily: theme.fontFamily,
      alignItems: 'center',
      justifyContent: 'center',
    }}
  >
    <Backdrop />
    {children}
  </AbsoluteFill>
);

export const BySoundSafe: React.FC<{ size?: number }> = ({ size = 84 }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 26 }}>
    <span style={{ fontSize: size * 0.5, fontWeight: 500, color: theme.darkTextSecondary }}>
      by
    </span>
    {/* the SoundSafe logotype is dark — give it a light pill so it reads */}
    <div
      style={{
        background: '#ffffff',
        borderRadius: 999,
        padding: `${size * 0.22}px ${size * 0.5}px`,
        display: 'flex',
        alignItems: 'center',
      }}
    >
      <Img src={staticFile('soundsafe-logo.png')} style={{ height: size }} />
    </div>
  </div>
);

/** 1 — logo + typeface + by SoundSafe */
export const PromoLogo: React.FC = () => (
  <Base>
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 90,
        zIndex: 1,
      }}
    >
      <div
        style={{
          width: 560,
          height: 560,
          borderRadius: 120,
          background: '#ffffff',
          boxShadow: '0 0 200px rgba(250,250,250,0.22), 0 60px 180px rgba(0,0,0,0.6)',
          overflow: 'hidden',
        }}
      >
        <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 560, height: 560 }} />
      </div>
      <div style={{ fontSize: 230, color: theme.darkText, letterSpacing: -5, lineHeight: 1 }}>
        <Wordmark />
      </div>
      <div style={{ height: 10, width: 620, borderRadius: 5, background: theme.highlight }} />
      <BySoundSafe size={104} />
    </div>
  </Base>
);

/** 2 — the tagline */
export const PromoTagline: React.FC = () => (
  <Base>
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 110,
        padding: '0 140px',
        zIndex: 1,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 40 }}>
        <div
          style={{
            width: 120,
            height: 120,
            borderRadius: 28,
            background: '#ffffff',
            overflow: 'hidden',
            flexShrink: 0,
          }}
        >
          <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 120, height: 120 }} />
        </div>
        <span style={{ fontSize: 96, color: theme.darkText, letterSpacing: -2 }}>
          <Wordmark />
        </span>
      </div>
      <div
        style={{
          fontSize: 218,
          fontWeight: 800,
          color: theme.darkText,
          letterSpacing: -4,
          lineHeight: 1.08,
          textAlign: 'center',
        }}
      >
        Unleash the power of{' '}
        <span style={{ color: theme.highlight }}>data correlation</span>
      </div>
      <div
        style={{
          fontSize: 66,
          fontWeight: 500,
          color: theme.darkTextSecondary,
          textAlign: 'center',
          lineHeight: 1.4,
        }}
      >
        Spreadsheets, PDFs, photos, audio, video & live sensor feeds —
        <br />
        one platform, one answer.
      </div>
      <BySoundSafe />
    </div>
  </Base>
);

/** 3 — Industry 4.0 mini-explainer + OmniusGrid as THE solution */
export const PromoIndustry: React.FC = () => (
  <Base>
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '150px 150px 130px',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 1,
      }}
    >
      <div
        style={{
          alignSelf: 'flex-start',
          padding: '20px 52px',
          borderRadius: 999,
          border: `3px solid ${theme.darkBorder}`,
          color: theme.darkTextSecondary,
          fontSize: 46,
          fontWeight: 700,
          letterSpacing: 8,
          textTransform: 'uppercase',
        }}
      >
        Industry 4.0
      </div>
      <div
        style={{
          marginTop: 84,
          fontSize: 168,
          fontWeight: 800,
          color: theme.darkText,
          letterSpacing: -3,
          lineHeight: 1.08,
        }}
      >
        The fourth industrial revolution runs on data.
      </div>
      <div
        style={{
          marginTop: 80,
          fontSize: 70,
          fontWeight: 500,
          color: 'rgba(250,250,250,0.82)',
          lineHeight: 1.48,
        }}
      >
        Enterprise data — ERP orders, invoices, shipments, quality records —
        holds half the story. Smart machines and smart factories produce the
        other half. The gains come when the two meet: transparency,
        flexibility, better decisions.
      </div>
      <div
        style={{
          marginTop: 72,
          fontSize: 70,
          fontWeight: 600,
          color: theme.darkText,
          lineHeight: 1.48,
        }}
      >
        But that data lives{' '}
        <span
          style={{
            background: '#ffffff',
            color: theme.darkBg,
            borderRadius: 18,
            padding: '2px 28px',
            fontWeight: 800,
          }}
        >
          scattered
        </span>{' '}
        — ERP, MES, spreadsheets, cameras, sensors.
      </div>
      <div style={{ flex: 1 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 34 }}>
        <div
          style={{
            width: 110,
            height: 110,
            borderRadius: 26,
            background: '#ffffff',
            overflow: 'hidden',
            flexShrink: 0,
          }}
        >
          <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 110, height: 110 }} />
        </div>
        <div style={{ fontSize: 92, fontWeight: 800, color: theme.darkText, letterSpacing: -1.5 }}>
          <Wordmark /> <span style={{ fontWeight: 600 }}>is the solution.</span>
        </div>
      </div>
      <div style={{ marginTop: 56, display: 'flex', flexDirection: 'column', gap: 40 }}>
        {[
          'Every format — Excel, PDFs, photos, audio, video, live sensors — one context',
          'Shop floor → logistics → financials → customer, correlated end-to-end',
          'Ask in plain language; get risk-scored answers with recommended actions',
        ].map((b) => (
          <div key={b} style={{ display: 'flex', alignItems: 'flex-start', gap: 30 }}>
            <div
              style={{
                width: 20,
                height: 20,
                borderRadius: 10,
                background: theme.highlight,
                marginTop: 26,
                flexShrink: 0,
                boxShadow: '0 0 22px rgba(59,130,246,0.6)',
              }}
            />
            <div
              style={{
                fontSize: 62,
                fontWeight: 500,
                color: 'rgba(250,250,250,0.9)',
                lineHeight: 1.38,
              }}
            >
              {b}
            </div>
          </div>
        ))}
      </div>
      <div
        style={{
          marginTop: 70,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div
          style={{
            padding: '22px 46px',
            borderRadius: 22,
            border: `3px solid rgba(59,130,246,0.55)`,
            background: 'rgba(59,130,246,0.10)',
            color: theme.highlightSoft,
            fontSize: 52,
            fontWeight: 700,
          }}
        >
          ⚡ The correlation engine for Industry 4.0
        </div>
        <BySoundSafe size={72} />
      </div>
    </div>
  </Base>
);
