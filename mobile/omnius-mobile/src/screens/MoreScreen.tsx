import React from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, Linking } from 'react-native';
import { useAuth } from '../context/AuthContext';
import { useTheme, useThemeColors } from '../context/ThemeContext';
import { AppButton } from '../components/AppButton';
import { SUPPORT_EMAIL, USE_DEMO_DATA } from '../config';
import { useDemoDataLayer } from '../api/dataLayer';
export function MoreScreen() {
  const c = useThemeColors();
  const { mode, setMode, isDark } = useTheme();
  const { user, logout, token } = useAuth();
  const demoLayer = useDemoDataLayer();

  return (
    <ScrollView style={{ flex: 1, backgroundColor: c.bg }} contentContainerStyle={styles.pad}>
      <Text style={[styles.h, { color: c.text }]}>Profile</Text>
      <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}>
        <Text style={[styles.name, { color: c.text }]}>{user?.full_name || 'Supervisor'}</Text>
        <Text style={[styles.meta, { color: c.muted }]}>{user?.email}</Text>
        <Text style={[styles.meta, { color: c.muted }]}>Role: {user?.role}</Text>
      </View>
      <AppButton title="Log out" variant="danger" onPress={() => void logout()} style={{ marginTop: 12 }} />

      <Text style={[styles.h, { color: c.text, marginTop: 28 }]}>Appearance</Text>
      <View style={styles.row}>
        {(['system', 'light', 'dark'] as const).map((m) => (
          <Pressable
            key={m}
            onPress={() => setMode(m)}
            style={[
              styles.modeBtn,
              { borderColor: c.border, backgroundColor: mode === m ? c.primary : c.card },
            ]}
          >
            <Text style={{ color: mode === m ? '#fff' : c.text, fontWeight: '700', textTransform: 'capitalize' }}>
              {m}
            </Text>
          </Pressable>
        ))}
      </View>
      <Text style={{ color: c.muted, marginTop: 8 }}>Currently: {isDark ? 'Dark' : 'Light'}</Text>

      <Text style={[styles.h, { color: c.text, marginTop: 28 }]}>Help</Text>
      <AppButton
        title="Contact admin (email)"
        variant="secondary"
        onPress={() => Linking.openURL(`mailto:${SUPPORT_EMAIL}`)}
      />

      <Text style={[styles.h, { color: c.text, marginTop: 28 }]}>App info</Text>
      <Text style={[styles.meta, { color: c.muted }]}>Omnius Grid Supervisor</Text>
      <Text style={[styles.meta, { color: c.muted }]}>Version 1.0.0</Text>
      <Text style={[styles.meta, { color: c.muted, marginTop: 12 }]}>
        API session:{' '}
        {token === 'dev-token'
          ? 'Dev shortcut (Bearer dev-token → real /auth/me; data from demo unless USE_DEMO_DATA=false)'
          : 'Standard JWT from /login'}
      </Text>
      <Text style={[styles.meta, { color: demoLayer ? c.text : c.muted, marginTop: 8 }]}>
        In-memory demo layer: {demoLayer ? 'ON (canned tasks, alerts, yard — like web mock mode)' : 'OFF'}
      </Text>
      {!USE_DEMO_DATA ? (
        <Text style={[styles.meta, { color: c.muted, marginTop: 6 }]}>
          Demo is off (you set EXPO_PUBLIC_USE_DEMO_DATA=false). Restart Expo after changing env. Data tiles use your
          API; `dev` login still uses the real backend for auth.
        </Text>
      ) : !demoLayer ? (
        <Text style={[styles.meta, { color: c.muted, marginTop: 6 }]}>
          Demo is enabled but the data layer is bypassed; try logging in again or restart the app.
        </Text>
      ) : (
        <Text style={[styles.meta, { color: c.muted, marginTop: 6 }]}>
          Default is demo on (no seeded DB needed). To load only live API data: set EXPO_PUBLIC_USE_DEMO_DATA=false and
          restart Expo. `dev` login still talks to /auth/me on your server.
        </Text>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  pad: { padding: 16, paddingBottom: 40 },
  h: { fontSize: 18, fontWeight: '800', marginBottom: 10 },
  card: { borderWidth: 1, borderRadius: 14, padding: 16 },
  name: { fontSize: 20, fontWeight: '800' },
  meta: { fontSize: 15, marginTop: 6 },
  row: { flexDirection: 'row', gap: 10, flexWrap: 'wrap' },
  modeBtn: {
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    borderWidth: 2,
  },
});
