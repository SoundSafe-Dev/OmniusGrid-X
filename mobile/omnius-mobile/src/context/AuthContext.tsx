import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import * as omnius from '../api/omniusApi';
import type { KanbanColumn, MeResponse, Task } from '../api/types';
import { clearStoredToken, getStoredToken, setStoredToken } from '../api/client';
import { setForceLiveApiData } from '../api/dataLayer';
import { USE_DEMO_DATA } from '../config';
import { useDemoLive } from '../demo/DemoLiveProvider';

type KanbanState = {
  columns: KanbanColumn[];
  tasks: Task[];
  loading: boolean;
  refresh: () => Promise<void>;
};

type AuthCtx = {
  ready: boolean;
  user: MeResponse | null;
  token: string | null;
  kanban: KanbanState;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

const DEV_WEB_TOKEN = 'dev-token';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { seq: demoLiveSeq } = useDemoLive();
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<MeResponse | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [columns, setColumns] = useState<KanbanColumn[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [kbLoading, setKbLoading] = useState(false);

  const refreshKanban = useCallback(async () => {
    if (!token) return;
    setKbLoading(true);
    try {
      const board = await omnius.fetchKanbanBoard();
      setColumns(board.columns);
      setTasks(board.tasks);
    } catch (e) {
      if (typeof __DEV__ !== 'undefined' && __DEV__) {
        console.warn('[kanban] fetch failed', e);
      }
      setColumns([]);
      setTasks([]);
    } finally {
      setKbLoading(false);
    }
  }, [token]);

  useEffect(() => {
    (async () => {
      const t = await getStoredToken();
      setToken(t);
      setForceLiveApiData(t === DEV_WEB_TOKEN && !USE_DEMO_DATA);
      if (t) {
        try {
          const me = await omnius.fetchMe();
          setUser(me);
        } catch {
          await clearStoredToken();
          setToken(null);
          setForceLiveApiData(false);
        }
      }
      setReady(true);
    })();
  }, []);

  useEffect(() => {
    if (token && user) {
      void refreshKanban();
    } else {
      setColumns([]);
      setTasks([]);
    }
  }, [token, user?.id, demoLiveSeq, refreshKanban]);

  const login = useCallback(async (email: string, password: string) => {
    const id = email.trim().toLowerCase();
    if (id === 'dev') {
      await setStoredToken(DEV_WEB_TOKEN);
      setForceLiveApiData(!USE_DEMO_DATA);
      setToken(DEV_WEB_TOKEN);
      const me = await omnius.fetchMe(DEV_WEB_TOKEN);
      setUser(me);
      return;
    }
    setForceLiveApiData(false);
    const tok = await omnius.loginRequest(email, password);
    await setStoredToken(tok.access_token);
    setToken(tok.access_token);
    const me = await omnius.fetchMe(tok.access_token);
    setUser(me);
  }, []);

  const logout = useCallback(async () => {
    await clearStoredToken();
    setForceLiveApiData(false);
    setToken(null);
    setUser(null);
    setColumns([]);
    setTasks([]);
  }, []);

  const refreshUser = useCallback(async () => {
    if (!token) return;
    const me = await omnius.fetchMe();
    setUser(me);
  }, [token]);

  const kanban = useMemo<KanbanState>(
    () => ({
      columns,
      tasks,
      loading: kbLoading,
      refresh: refreshKanban,
    }),
    [columns, tasks, kbLoading, refreshKanban]
  );

  const value = useMemo(
    () => ({
      ready,
      user,
      token,
      kanban,
      login,
      logout,
      refreshUser,
    }),
    [ready, user, token, kanban, login, logout, refreshUser]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside AuthProvider');
  return v;
}
