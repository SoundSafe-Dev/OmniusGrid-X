import React, { useEffect, useRef, useState } from 'react';
import { AbsoluteFill, continueRender, delayRender } from 'remotion';
import { QueryClient, QueryClientProvider, useIsFetching } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { TooltipProvider } from '../../src/components/ui';
import { theme, STAGE_W, STAGE_H, STAGE_SCALE, CHROME_H } from './theme';
import '../../src/index.css';

/**
 * Wraps a real app page for rendering inside a Remotion composition:
 * - QueryClient with polling/retries off (deterministic frames)
 * - MemoryRouter + TooltipProvider (the providers pages actually need)
 * - light-theme guard (removes any stray `.dark` on the root element)
 * - kills the app's wall-clock CSS animations (chunk-seam shimmer)
 * - 1920x1080 stage scaled 2x so text rasterizes crisply at 4K
 * - browser-chrome bar with the page's route
 * - delayRender "settle gate": holds frame capture until react-query and
 *   the microtask-resolved mock fetchers have gone quiet for 500ms
 */

const SETTLE_QUIET_MS = 500;
const SETTLE_HARD_CAP_MS = 8000;

// scrollIntoView (e.g. the chat's scroll-to-bottom) also scrolls overflow:hidden
// ancestors — once PanZoom scales the page beyond the stage box, that box becomes
// programmatically scrollable and the page fights the camera. The video never
// needs real scrolling, so disable it globally in this bundle.
if (typeof Element !== 'undefined') {
  Element.prototype.scrollIntoView = () => {};
}

export const SettleGate: React.FC = () => {
  const isFetching = useIsFetching();
  const [handle] = useState(() => delayRender('page settle'));
  const doneRef = useRef(false);
  const fetchingRef = useRef(isFetching);
  fetchingRef.current = isFetching;

  useEffect(() => {
    const finish = () => {
      if (!doneRef.current) {
        doneRef.current = true;
        continueRender(handle);
      }
    };

    const hardCap = window.setTimeout(finish, SETTLE_HARD_CAP_MS);
    // Quiet = no react-query fetches AND no Leaflet tiles still loading
    // (the TMS map pulls OSM tiles over the network during render).
    let quietSince: number | null = null;
    const poll = window.setInterval(() => {
      const tilesPending =
        document.querySelectorAll('.leaflet-tile:not(.leaflet-tile-loaded)').length > 0;
      if (fetchingRef.current > 0 || tilesPending) {
        quietSince = null;
        return;
      }
      const now = performance.now();
      if (quietSince === null) {
        quietSince = now;
      } else if (now - quietSince >= SETTLE_QUIET_MS) {
        finish();
      }
    }, 100);
    return () => {
      window.clearTimeout(hardCap);
      window.clearInterval(poll);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle]);

  // Ensure the handle is released even if the scene unmounts first
  useEffect(() => {
    return () => {
      if (!doneRef.current) {
        doneRef.current = true;
        continueRender(handle);
      }
    };
  }, [handle]);

  return null;
};

export const BrowserChrome: React.FC<{ route: string }> = ({ route }) => (
  <div
    style={{
      height: CHROME_H,
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      padding: '0 16px',
      background: theme.panel,
      borderBottom: `1px solid ${theme.border}`,
      fontFamily: theme.fontFamily,
    }}
  >
    <div style={{ display: 'flex', gap: 7 }}>
      {['#f87171', '#fbbf24', '#34d399'].map((c) => (
        <div key={c} style={{ width: 12, height: 12, borderRadius: 6, background: c }} />
      ))}
    </div>
    <div
      style={{
        flex: 1,
        maxWidth: 560,
        margin: '0 auto',
        height: 28,
        borderRadius: 14,
        background: theme.hover,
        border: `1px solid ${theme.border}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 13,
        color: theme.textSecondary,
        letterSpacing: 0.2,
      }}
    >
      app.omniusgrid.io{route}
    </div>
    <div style={{ width: 50 }} />
  </div>
);

// Freeze wall-clock CSS animations, and re-map viewport-height layouts
// (e.g. CorrelationAIPane's h-[calc(100vh-2rem)]) to the stage box — inside
// the 2x-scaled stage, 100vh would resolve against the 4K viewport and
// overflow the visible area.
export const STAGE_CSS = `
  .og-video-stage *, .og-video-stage *::before, .og-video-stage *::after {
    animation: none !important;
    transition: none !important;
    caret-color: transparent !important;
  }
  .og-video-stage [class*='100vh'] {
    height: 100% !important;
    max-height: 100% !important;
  }
  .og-video-stage [class*='min-h-screen'] {
    min-height: 100% !important;
  }
  .og-video-stage ::-webkit-scrollbar { display: none; }
`;

interface AppFrameProps {
  route: string;
  children: React.ReactNode;
  /** Extra CSS scoped to this scene (e.g. hiding the Leaflet map) */
  extraCss?: string;
  /** Give the page an explicit stage-height box (for 100vh-based pages) */
  fitHeight?: boolean;
}

export const AppFrame: React.FC<AppFrameProps> = ({ route, children, extraCss, fitHeight }) => {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            refetchInterval: false,
            refetchOnWindowFocus: false,
            staleTime: Infinity,
          },
        },
      })
  );

  useEffect(() => {
    // The video is light mode; guard against anything toggling the dark class
    document.documentElement.classList.remove('dark');
  }, []);

  return (
    <AbsoluteFill style={{ background: theme.bg }}>
      <style>{STAGE_CSS}</style>
      {extraCss ? <style>{extraCss}</style> : null}
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>
          <TooltipProvider>
            <SettleGate />
            <div
              className="og-video-stage"
              style={{
                width: STAGE_W,
                height: STAGE_H,
                transform: `scale(${STAGE_SCALE})`,
                transformOrigin: 'top left',
                background: theme.bg,
                fontFamily: theme.fontFamily,
              }}
            >
              <BrowserChrome route={route} />
              <div
                style={{
                  width: STAGE_W,
                  height: STAGE_H - CHROME_H,
                  overflow: 'hidden',
                  position: 'relative',
                  background: theme.bg,
                }}
              >
                <div style={fitHeight ? { height: '100%', padding: 12 } : { padding: 16 }}>
                  {children}
                </div>
              </div>
            </div>
          </TooltipProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </AbsoluteFill>
  );
};
