import { Platform } from 'react-native';

/** Android emulator reaches the dev machine via this alias (not localhost). */
const defaultHost =
  Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://localhost:8000';

/** If EXPO_PUBLIC_API_URL uses localhost on Android, requests hit the emulator itself. */
function normalizeEnvApiUrl(url: string): string {
  const trimmed = url.trim().replace(/\/+$/, '');
  if (Platform.OS !== 'android' || !trimmed) {
    return trimmed;
  }
  try {
    const u = new URL(/^[a-z]+:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`);
    if (u.hostname === 'localhost' || u.hostname === '127.0.0.1') {
      u.hostname = '10.0.2.2';
      return u.origin;
    }
  } catch {
    /* keep trimmed */
  }
  return trimmed;
}

const envOverride = process.env.EXPO_PUBLIC_API_URL?.trim();
export const API_BASE =
  envOverride && envOverride.length > 0 ? normalizeEnvApiUrl(envOverride) : defaultHost;

export const SUPPORT_EMAIL = 'ops-admin@omniusgrid.com';

/**
 * In-memory demo dataset (same style as web VITE_USE_MOCK): tasks, yard, alerts, dashboard tiles.
 * Login still uses the real API; only data reads can be demo-backed.
 *
 * Default ON so supervisor Home is populated without a seeded DB. For live Postgres/API data only:
 *   EXPO_PUBLIC_USE_DEMO_DATA=false
 */
const demoEnv = process.env.EXPO_PUBLIC_USE_DEMO_DATA?.trim().toLowerCase();
export const USE_DEMO_DATA = demoEnv !== 'false' && demoEnv !== '0';
