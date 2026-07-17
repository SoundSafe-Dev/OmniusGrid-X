import React, { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { TooltipProvider } from '../../../../src/components/ui';
import { theme, CHROME_H } from '../../theme';
import { SettleGate, BrowserChrome, STAGE_CSS } from '../../AppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { PanZoomMove } from '../../components/PanZoom';
import { PAGE_W, PAGE_H } from '../theme';
import '../../../../src/index.css';

/**
 * A TALL portrait window onto a desktop page, for the mobile framed scenes:
 * chrome bar + a portrait viewport whose camera pans/zooms over the 1920-wide
 * desktop layout. Shows page content ~2x larger than the old 16:9 mini card
 * while still reading as a desktop browser.
 *
 * `width`/`height` are canvas px; the internal stage is width/2 x height/2
 * (scaled 2x), so the camera viewport is (width/2) x (height/2 - CHROME_H)
 * in stage px — pass moves with focus coords in page space, as everywhere.
 */
interface MiniPortraitStageProps {
  route: string;
  width: number;
  height: number;
  children: React.ReactNode;
  moves?: PanZoomMove[];
  overlays?: React.ReactNode;
  stageOverlay?: React.ReactNode;
  extraCss?: string;
  fitHeight?: boolean;
}

export const MiniPortraitStage: React.FC<MiniPortraitStageProps> = ({
  route,
  width,
  height,
  children,
  moves,
  overlays,
  stageOverlay,
  extraCss,
  fitHeight,
}) => {
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
  const stageW = width / 2;
  const stageH = height / 2;
  const viewH = stageH - CHROME_H;

  return (
    <div style={{ width, height, overflow: 'hidden', background: theme.bg }}>
      <style>{STAGE_CSS}</style>
      {extraCss ? <style>{extraCss}</style> : null}
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>
          <TooltipProvider>
            <SettleGate />
            <div
              className="og-video-stage"
              style={{
                width: stageW,
                height: stageH,
                transform: 'scale(2)',
                transformOrigin: 'top left',
                background: theme.bg,
                fontFamily: theme.fontFamily,
              }}
            >
              <BrowserChrome route={route} />
              <div
                style={{
                  width: stageW,
                  height: viewH,
                  overflow: 'hidden',
                  position: 'relative',
                  background: theme.bg,
                }}
              >
                <div
                  style={
                    fitHeight
                      ? { width: PAGE_W, height: PAGE_H, padding: 12 }
                      : { width: PAGE_W, padding: 16 }
                  }
                >
                  <MobilePanZoom
                    entrance={false}
                    viewW={stageW}
                    viewH={viewH}
                    moves={moves ?? [{ at: 0, scale: stageW / PAGE_W, focusX: 960, focusY: 518 }]}
                  >
                    {children}
                    {overlays}
                  </MobilePanZoom>
                </div>
                {stageOverlay}
              </div>
            </div>
          </TooltipProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </div>
  );
};
