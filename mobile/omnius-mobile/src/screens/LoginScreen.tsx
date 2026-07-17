import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  Pressable,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from 'react-native';
import type { StackScreenProps } from '@react-navigation/stack';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { useThemeColors } from '../context/ThemeContext';
import { AppButton } from '../components/AppButton';
import demo from '../fixtures/demoUser.json';
import type { ApiError } from '../api/client';
import { API_BASE } from '../config';

import type { AuthStackParamList } from '../navigation/types';

type Props = StackScreenProps<AuthStackParamList, 'Login'>;

export function LoginScreen({ navigation }: Props) {
  const c = useThemeColors();
  const { login } = useAuth();
  const toast = useToast();
  const [email, setEmail] = useState(demo.email);
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [topErr, setTopErr] = useState<string | null>(null);

  const onSubmit = async () => {
    setTopErr(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      toast.show('Signed in');
    } catch (e: unknown) {
      const api = e as Partial<ApiError>;
      if (typeof api.status === 'number' && api.message) {
        setTopErr(api.status === 401 ? api.message : `${api.message} (${api.status})`);
      } else if (e instanceof TypeError || (e instanceof Error && /Network|Failed to fetch|load failed/i.test(e.message))) {
        const androidDetail =
          API_BASE.includes('10.0.2.2') || API_BASE.includes('10.0.3.2')
            ? 'Start the API on this Mac (e.g. from repo root: docker compose up backend). On the Mac, curl http://127.0.0.1:8000/docs should return HTML. Genymotion often needs EXPO_PUBLIC_API_URL=http://10.0.3.2:8000 instead of 10.0.2.2.'
            : 'Android emulator usually uses http://10.0.2.2:8000; a physical phone needs your Mac’s Wi‑Fi IP.';
        const hint = Platform.OS === 'android' ? androidDetail : 'iOS simulator: http://localhost:8000. iOS device: set EXPO_PUBLIC_API_URL to your Mac’s LAN IP:8000.';
        setTopErr(`No response from ${API_BASE}. ${hint}`);
      } else {
        setTopErr('Invalid login, please try again');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: c.bg }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.logoBlock}>
          <Text style={[styles.logoMark, { color: c.primary }]}>OG</Text>
          <Text style={[styles.appName, { color: c.text }]}>Omnius Grid</Text>
          <Text style={[styles.sub, { color: c.muted }]}>Supervisor</Text>
          <Text style={[styles.hint, { color: c.muted }]}>
            Same data as the web app: use dev + any password (matches web DEV MODE). Or use your real email and password (e.g. omnius@omniusgrid.com).
          </Text>
        </View>

        {topErr ? (
          <View style={[styles.errBanner, { borderColor: c.danger }]}>
            <Text style={[styles.errText, { color: c.danger }]}>{topErr}</Text>
          </View>
        ) : null}

        <Text style={[styles.label, { color: c.text }]}>Email or username</Text>
        <TextInput
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          placeholder="dev or you@company.com"
          placeholderTextColor={c.muted}
          style={[styles.input, { color: c.text, borderColor: c.border, backgroundColor: c.card }]}
        />

        <Text style={[styles.label, { color: c.text }]}>Password</Text>
        <View style={[styles.pwRow, { borderColor: c.border, backgroundColor: c.card }]}>
          <TextInput
            value={password}
            onChangeText={setPassword}
            secureTextEntry={!showPw}
            placeholder="••••••••"
            placeholderTextColor={c.muted}
            style={[styles.inputInline, { color: c.text }]}
          />
          <Pressable onPress={() => setShowPw(!showPw)} hitSlop={12}>
            <Text style={{ color: c.primary, fontWeight: '700' }}>{showPw ? 'Hide' : 'Show'}</Text>
          </Pressable>
        </View>

        <AppButton title="Log In" onPress={onSubmit} loading={busy} style={{ marginTop: 20 }} />

        <View style={styles.links}>
          <Pressable onPress={() => navigation.navigate('ForgotPassword')}>
            <Text style={[styles.link, { color: c.primary }]}>Forgot password?</Text>
          </Pressable>
          <Pressable onPress={() => navigation.navigate('ContactAdmin')}>
            <Text style={[styles.link, { color: c.primary }]}>Contact admin</Text>
          </Pressable>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: 20, paddingTop: 48, flexGrow: 1 },
  logoBlock: { alignItems: 'center', marginBottom: 32 },
  logoMark: {
    fontSize: 42,
    fontWeight: '900',
    letterSpacing: -1,
  },
  appName: { fontSize: 26, fontWeight: '800', marginTop: 8 },
  sub: { fontSize: 16, marginTop: 4 },
  hint: { fontSize: 14, marginTop: 12, textAlign: 'center', lineHeight: 20, paddingHorizontal: 8 },
  label: { fontSize: 15, fontWeight: '600', marginBottom: 6, marginTop: 12 },
  input: {
    borderWidth: 2,
    borderRadius: 12,
    minHeight: 52,
    paddingHorizontal: 14,
    fontSize: 17,
  },
  pwRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 2,
    borderRadius: 12,
    paddingRight: 12,
  },
  inputInline: { flex: 1, minHeight: 52, paddingHorizontal: 14, fontSize: 17 },
  links: { marginTop: 24, gap: 14 },
  link: { fontSize: 15, fontWeight: '600' },
  errBanner: {
    borderWidth: 2,
    borderRadius: 12,
    padding: 12,
    marginBottom: 8,
  },
  errText: { fontSize: 16, fontWeight: '600', textAlign: 'center' },
});
