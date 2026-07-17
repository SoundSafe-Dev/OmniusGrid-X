import React, { createContext, useContext, useMemo, useState } from 'react';
import { useColorScheme } from 'react-native';

export type ThemeMode = 'light' | 'dark' | 'system';

type ThemeColors = {
  bg: string;
  card: string;
  text: string;
  muted: string;
  border: string;
  primary: string;
  primaryText: string;
  chip: string;
  danger: string;
  success: string;
  warning: string;
  toastBg: string;
};

const light: ThemeColors = {
  bg: '#F4F6F8',
  card: '#FFFFFF',
  text: '#111827',
  muted: '#6B7280',
  border: '#E5E7EB',
  primary: '#1D4ED8',
  primaryText: '#FFFFFF',
  chip: '#EEF2FF',
  danger: '#B91C1C',
  success: '#047857',
  warning: '#B45309',
  toastBg: '#ECFDF5',
};

const dark: ThemeColors = {
  bg: '#0F172A',
  card: '#1E293B',
  text: '#F8FAFC',
  muted: '#94A3B8',
  border: '#334155',
  primary: '#3B82F6',
  primaryText: '#FFFFFF',
  chip: '#312E81',
  danger: '#F87171',
  success: '#34D399',
  warning: '#FBBF24',
  toastBg: '#064E3B',
};

type Ctx = {
  mode: ThemeMode;
  setMode: (m: ThemeMode) => void;
  colors: ThemeColors;
  isDark: boolean;
};

const ThemeCtx = createContext<Ctx | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const system = useColorScheme();
  const [mode, setMode] = useState<ThemeMode>('system');

  const isDark = mode === 'dark' || (mode === 'system' && system === 'dark');

  const colors = useMemo(() => {
    return isDark ? dark : light;
  }, [isDark]);

  const value = useMemo(() => ({ mode, setMode, colors, isDark }), [mode, colors, isDark]);

  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export function useTheme() {
  const v = useContext(ThemeCtx);
  if (!v) throw new Error('useTheme outside ThemeProvider');
  return v;
}

export function useThemeColors() {
  return useTheme().colors;
}
