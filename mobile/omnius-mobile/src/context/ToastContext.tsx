import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { useThemeColors } from './ThemeContext';

type ToastCtx = { show: (msg: string) => void; error: (msg: string) => void };

const Ctx = createContext<ToastCtx | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const colors = useThemeColors();

  const show = useCallback((m: string) => {
    setIsError(false);
    setMsg(m);
    setTimeout(() => setMsg(null), 2800);
  }, []);

  const error = useCallback((m: string) => {
    setIsError(true);
    setMsg(m);
    setTimeout(() => setMsg(null), 4000);
  }, []);

  const value = useMemo(() => ({ show, error }), [show, error]);

  return (
    <Ctx.Provider value={value}>
      {children}
      {msg ? (
        <View style={styles.wrap} pointerEvents="box-none">
          <Pressable
            onPress={() => setMsg(null)}
            style={[
              styles.banner,
              { backgroundColor: isError ? colors.danger : colors.toastBg, borderColor: colors.border },
            ]}
          >
            <Text style={[styles.text, { color: isError ? '#fff' : colors.text }]}>{msg}</Text>
          </Pressable>
        </View>
      ) : null}
    </Ctx.Provider>
  );
}

export function useToast() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useToast outside ToastProvider');
  return v;
}

const styles = StyleSheet.create({
  wrap: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: 'flex-end',
    padding: 16,
    paddingBottom: 32,
  },
  banner: {
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 12,
    borderWidth: 1,
    minHeight: 48,
    justifyContent: 'center',
  },
  text: { fontSize: 16, fontWeight: '600' },
});
