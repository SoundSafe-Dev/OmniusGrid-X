import React, { useState } from 'react';
import { QueryClient, QueryClientProvider } from 'react-query';
import { MemoryRouter } from 'react-router-dom';
import { TooltipProvider } from '../../../src/components/ui';
import { theme, STAGE_W, STAGE_H, CHROME_H } from '../theme';
import { SettleGate, BrowserChrome, STAGE_CSS } from '../AppFrame';
import { PanZoom, PanZoomMove } from './PanZoom';
import '../../../src/index.css';

/**
 * A page rendered as a scaled stage of arbitrary width (chrome bar + page),
 * for framed layouts and the stack finale. Same provider/settle/CSS setup as
 * the full-bleed AppFrame, sized by `width` (4K px).
 */
interface MiniStageProps {
  route: string;
  width: number;
  children: React.ReactNode;
  /** Internal camera; defaults to static full view */
  moves?: PanZoomMove[];
  /** Overlays inside the camera space (Highlights, cursors) */
  overlays?: React.ReactNode;
  /** Overlays in stage coordinates above the camera (e.g. NavDrawer) */
  stageOverlay?: React.ReactNode;
  extraCss?: string;
  fitHeight?: boolean;
}

export const MINI_STAGE_RATIO = STAGE_H / STAGE_W; // height = width * ratio

export const MiniStage: React.FC<MiniStageProps> = ({
  route,
  width,
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
  const scale = width / STAGE_W;

  return (
    <div style={{ width, height: STAGE_H * scale, overflow: 'hidden', background: theme.bg }}>
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
                transform: `scale(${scale})`,
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
                  <PanZoom
                    entrance={false}
                    moves={moves ?? [{ at: 0, scale: 1, focusX: 960, focusY: 518 }]}
                  >
                    {children}
                    {overlays}
                  </PanZoom>
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
