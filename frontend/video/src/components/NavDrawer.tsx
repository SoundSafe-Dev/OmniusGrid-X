import React from 'react';
import { Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';
import {
  LayoutDashboard,
  Box,
  Bell,
  BarChart3,
  Kanban as KanbanIcon,
  MessageSquare,
  Inbox,
  Warehouse,
  Truck,
  Database,
} from 'lucide-react';
import { theme, STAGE_H, CHROME_H } from '../theme';
import { Cursor } from './Interactions';
import { Wordmark } from './Wordmark';

/**
 * Page-to-page navigation moment: a pixel-faithful replica of the app's
 * sidebar (same Tailwind classes / icons / labels / order as
 * src/components/layout/Sidebar.tsx) slides in over the page's left edge,
 * the cursor hovers the destination item, clicks, and the scene transition
 * carries the navigation. Frame-driven hover/active states.
 */

type NavEntry =
  | { kind: 'item'; path: string; label: string; icon: React.FC<any>; sub?: boolean }
  | { kind: 'section'; label: string };

const NAV: NavEntry[] = [
  { kind: 'item', path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { kind: 'item', path: '/assets', label: 'Assets', icon: Box },
  { kind: 'item', path: '/alarms', label: 'Alarms', icon: Bell },
  { kind: 'item', path: '/oee', label: 'OEE', icon: BarChart3 },
  { kind: 'item', path: '/kanban', label: 'Kanban Board', icon: KanbanIcon },
  { kind: 'item', path: '/nlp', label: 'Correlation AI', icon: MessageSquare },
  { kind: 'item', path: '/intake', label: 'Intake Inbox', icon: Inbox },
  { kind: 'section', label: 'Logistics' },
  { kind: 'item', path: '/logistics/yard', label: 'Yard (YMS)', icon: Warehouse, sub: true },
  { kind: 'item', path: '/logistics/transportation', label: 'Transportation (TMS)', icon: Truck, sub: true },
  { kind: 'item', path: '/erp', label: 'ERP', icon: Database },
];

const DRAWER_W = 264;
const HEADER_H = 78;
const PAD = 12;
const ITEM_H = 48;
const SUB_H = 40;
const SECTION_H = 34;
const GAP = 4;

const entryHeight = (e: NavEntry) =>
  e.kind === 'section' ? SECTION_H : e.sub ? SUB_H : ITEM_H;

/** Stage-Y of an item's center (drawer coordinate space, below chrome). */
export const navItemCenterY = (path: string): number => {
  let y = HEADER_H + PAD;
  for (const e of NAV) {
    const h = entryHeight(e);
    if (e.kind === 'item' && e.path === path) return y + h / 2;
    y += h + GAP;
  }
  return y;
};

interface NavDrawerProps {
  /** Route of the page currently on screen (rendered as active) */
  activePath: string;
  /** Route being navigated to (hovered + clicked) */
  targetPath: string;
  /** Scene-local frame the drawer starts sliding in */
  inAt: number;
  /** Scene-local frame of the click (hover starts ~12f before) */
  clickAt: number;
}

export const NavDrawer: React.FC<NavDrawerProps> = ({ activePath, targetPath, inAt, clickAt }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame < inAt - 2) return null;

  const slide = spring({
    frame: frame - inAt,
    fps,
    config: { damping: 17, stiffness: 140 },
    durationInFrames: 16,
  });
  const tx = interpolate(slide, [0, 1], [-DRAWER_W - 30, 0]);
  const hoverOn = frame >= clickAt - 12;
  const targetY = navItemCenterY(targetPath);

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 60, pointerEvents: 'none' }}>
      <div
        className="og-video-stage"
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: DRAWER_W,
          height: STAGE_H - CHROME_H,
          transform: `translateX(${tx}px)`,
          background: theme.panel,
          borderRight: `1px solid ${theme.border}`,
          boxShadow: '18px 0 60px rgba(0,0,0,0.18)',
          fontFamily: theme.fontFamily,
          overflow: 'hidden',
        }}
      >
        {/* header — logo + wordmark, like the app chrome */}
        <div
          style={{
            height: HEADER_H,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '0 16px',
            borderBottom: `1px solid ${theme.border}`,
          }}
        >
          <div
            style={{
              width: 42,
              height: 42,
              borderRadius: 10,
              overflow: 'hidden',
              border: `1px solid ${theme.border}`,
              background: '#fff',
              flexShrink: 0,
            }}
          >
            <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 42, height: 42 }} />
          </div>
          <span style={{ fontSize: 19, color: theme.text, letterSpacing: -0.4 }}>
            <Wordmark boldWeight={700} />
          </span>
        </div>
        {/* nav list — classes mirror the real Sidebar */}
        <div style={{ padding: PAD, display: 'flex', flexDirection: 'column', gap: GAP }}>
          {NAV.map((e) => {
            if (e.kind === 'section') {
              return (
                <div
                  key={e.label}
                  className="px-4 text-xs font-medium text-opsgrid-text-secondary uppercase tracking-wider"
                  style={{ height: SECTION_H, display: 'flex', alignItems: 'center' }}
                >
                  {e.label}
                </div>
              );
            }
            const Icon = e.icon;
            const isActive = e.path === activePath;
            const isHovered = hoverOn && e.path === targetPath;
            return (
              <div
                key={e.path}
                className={`flex items-center gap-3 px-4 rounded-lg ${
                  isActive
                    ? 'bg-opsgrid-primary/20 text-opsgrid-primary'
                    : isHovered
                      ? 'bg-opsgrid-border text-opsgrid-text'
                      : 'text-opsgrid-text-secondary'
                } ${e.sub ? 'ml-4' : ''}`}
                style={{ height: e.sub ? SUB_H : ITEM_H }}
              >
                <Icon size={e.sub ? 18 : 20} />
                <span style={{ fontSize: e.sub ? 14 : 15, fontWeight: isActive ? 600 : 500 }}>
                  {e.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      {/* cursor flies in from the page and clicks the target item */}
      <Cursor
        path={[
          { at: inAt + 2, x: 640, y: targetY + 120 },
          { at: clickAt - 10, x: 132, y: targetY },
          { at: clickAt + 10, x: 132, y: targetY },
        ]}
        clicks={[clickAt]}
        inAt={inAt + 2}
      />
    </div>
  );
};
