import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { USE_DEMO_DATA } from '../config';
import { isForceLiveApiData } from '../api/dataLayer';
import { applyDemoLiveTick } from './store';

type DemoLive = { seq: number; enabled: boolean };

const DemoLiveContext = createContext<DemoLive>({ seq: 0, enabled: false });

export function DemoLiveProvider({ children }: { children: React.ReactNode }) {
  const [seq, setSeq] = useState(0);
  const enabled = USE_DEMO_DATA;

  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => {
      if (isForceLiveApiData()) return;
      applyDemoLiveTick();
      setSeq((s) => s + 1);
    }, 4500);
    return () => clearInterval(id);
  }, [enabled]);

  const value = useMemo(() => ({ seq, enabled }), [seq, enabled]);
  return <DemoLiveContext.Provider value={value}>{children}</DemoLiveContext.Provider>;
}

export function useDemoLive(): DemoLive {
  return useContext(DemoLiveContext);
}
