import React from 'react';
import { Img, staticFile } from 'remotion';
import { theme } from '../theme';
import { Wordmark } from '../components/Wordmark';
import { Base, BySoundSafe } from './PromoCards';
import { CorrelationAnswer } from './DeckCards';

/**
 * Marketing collateral beyond the decks:
 * - OnePager: 2550x3300 (US Letter @300dpi) sales leave-behind
 * - BannerLinkedIn: 3168x792 (2x LinkedIn company cover 1584x396)
 */

// ------------------------------------------------------------- one-pager

export const OnePager: React.FC = () => (
  <Base>
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '110px 130px',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 1,
      }}
    >
      {/* header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 30 }}>
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
          <span style={{ fontSize: 92, color: theme.darkText, letterSpacing: -2 }}>
            <Wordmark />
          </span>
        </div>
        <BySoundSafe size={60} />
      </div>
      {/* hook */}
      <div
        style={{
          marginTop: 90,
          fontSize: 128,
          fontWeight: 800,
          color: theme.darkText,
          letterSpacing: -2.5,
          lineHeight: 1.08,
        }}
      >
        Just ask. <span style={{ color: theme.highlight }}>It correlates.</span>
      </div>
      <div
        style={{
          marginTop: 44,
          fontSize: 54,
          fontWeight: 500,
          color: 'rgba(250,250,250,0.85)',
          lineHeight: 1.45,
        }}
      >
        OmniusGrid correlates enterprise data — ERP orders, invoices, shipments,
        quality records — with live machine data from the floor. Every answer
        shows its reasoning, carries a score, and ships with a one-click action.
      </div>
      {/* the product */}
      <div style={{ marginTop: 70, flex: 1, display: 'flex' }}>
        <CorrelationAnswer />
      </div>
      {/* pillars */}
      <div style={{ marginTop: 70, display: 'flex', gap: 50 }}>
        {(
          [
            ['Optimized Operations.', 'True load, health and headroom of every line — grow on evidence, not intuition.'],
            ['Actionable Insights.', 'GO / risk scores, one-click approval, Kanban dispatch to any department.'],
            ['Maximum Efficiency.', 'TMS, YMS and delivery capacity in one picture — commit knowing OTIF holds.'],
          ] as [string, string][]
        ).map(([h, b]) => (
          <div
            key={h}
            style={{
              flex: 1,
              borderRadius: 28,
              border: `3px solid ${theme.darkBorder}`,
              background: 'rgba(255,255,255,0.03)',
              padding: '50px 54px',
              display: 'flex',
              flexDirection: 'column',
              gap: 24,
            }}
          >
            <div style={{ fontSize: 54, fontWeight: 800, color: theme.darkText, letterSpacing: -1 }}>
              {h}
            </div>
            <div style={{ fontSize: 38, fontWeight: 500, color: 'rgba(250,250,250,0.82)', lineHeight: 1.45 }}>
              {b}
            </div>
          </div>
        ))}
      </div>
      {/* footer */}
      <div
        style={{
          marginTop: 80,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div
          style={{
            padding: '24px 52px',
            borderRadius: 22,
            border: `3px solid rgba(59,130,246,0.55)`,
            background: 'rgba(59,130,246,0.10)',
            color: theme.highlightSoft,
            fontSize: 48,
            fontWeight: 700,
          }}
        >
          ⚡ See your own data correlated — book a live session
        </div>
        <div style={{ fontSize: 44, color: theme.darkText, fontWeight: 700 }}>
          <Wordmark />
        </div>
      </div>
    </div>
  </Base>
);

// -------------------------------------------------------- LinkedIn banner

export const BannerLinkedIn: React.FC = () => (
  <Base>
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '90px 140px',
        display: 'flex',
        alignItems: 'center',
        gap: 110,
        zIndex: 1,
      }}
    >
      {/* LinkedIn crops the lower-left behind the page avatar — keep it clear */}
      <div style={{ width: 560, flexShrink: 0 }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 40, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 36 }}>
          <div
            style={{
              width: 130,
              height: 130,
              borderRadius: 30,
              background: '#ffffff',
              overflow: 'hidden',
              flexShrink: 0,
            }}
          >
            <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 130, height: 130 }} />
          </div>
          <span style={{ fontSize: 120, color: theme.darkText, letterSpacing: -2.5 }}>
            <Wordmark />
          </span>
        </div>
        <div
          style={{
            fontSize: 88,
            fontWeight: 800,
            color: theme.darkText,
            letterSpacing: -1.5,
            lineHeight: 1.1,
          }}
        >
          Unleash the power of{' '}
          <span style={{ color: theme.highlight }}>data correlation</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
          {(
            [
              ['XLSX', 'blue'],
              ['PDF', 'blue'],
              ['● LIVE', 'green'],
              ['7 ERPs', 'neutral'],
              ['TMS', 'neutral'],
              ['YMS', 'neutral'],
              ['OEE', 'neutral'],
            ] as [string, 'blue' | 'green' | 'neutral'][]
          ).map(([label, tone]) => (
            <span
              key={label}
              style={{
                padding: '12px 30px',
                borderRadius: 999,
                border: `3px solid ${
                  tone === 'green'
                    ? 'rgba(74,222,128,0.5)'
                    : tone === 'blue'
                      ? 'rgba(59,130,246,0.45)'
                      : theme.darkBorder
                }`,
                background:
                  tone === 'green'
                    ? 'rgba(74,222,128,0.08)'
                    : tone === 'blue'
                      ? 'rgba(59,130,246,0.08)'
                      : 'transparent',
                color:
                  tone === 'green'
                    ? '#4ade80'
                    : tone === 'blue'
                      ? theme.highlightSoft
                      : theme.darkTextSecondary,
                fontSize: 38,
                fontWeight: tone === 'neutral' ? 600 : 700,
                whiteSpace: 'nowrap',
              }}
            >
              {label}
            </span>
          ))}
        </div>
      </div>
      <div style={{ alignSelf: 'flex-end', paddingBottom: 10 }}>
        <BySoundSafe size={56} />
      </div>
    </div>
  </Base>
);
