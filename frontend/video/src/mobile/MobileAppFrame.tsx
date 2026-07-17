import React, { useEffect, useState } from 'react';
import { AbsoluteFill } from 'remotion';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { TooltipProvider } from '../../../src/components/ui';
import { theme, CHROME_H } from '../theme';
import { SettleGate, BrowserChrome, STAGE_CSS } from '../AppFrame';
import { M_STAGE_W, M_STAGE_H, M_STAGE_SCALE, PAGE_W, PAGE_H } from './theme';
import '../../../src/index.css';

/**
 * Portrait (9:16) wrapper for a real app page. Same providers / settle gate /
 * frozen-animation CSS as the desktop AppFrame, but the stage is 1080x1920
 * (scaled 2x to 2160x3840) and the page keeps its DESKTOP 1920-wide layout —
 * the MobilePanZoom camera pans a portrait window over it. fitHeight pins the
 * page box to the desktop 1036px height so pages render pixel-identically to
 * the landscape edition.
 */
interface MobileAppFrameProps {
  route: string;
  children: React.ReactNode;
  extraCss?: string;
  fitHeight?: boolean;
}

export const MobileAppFrame: React.FC<MobileAppFrameProps> = ({
  route,
  children,
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

  useEffect(() => {
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
                width: M_STAGE_W,
                height: M_STAGE_H,
                transform: `scale(${M_STAGE_SCALE})`,
                transformOrigin: 'top left',
                background: theme.bg,
                fontFamily: theme.fontFamily,
              }}
            >
              <BrowserChrome route={route} />
              <div
                style={{
                  width: M_STAGE_W,
                  height: M_STAGE_H - CHROME_H,
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
