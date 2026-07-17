import * as SecureStore from 'expo-secure-store';
import { API_BASE } from '../config';

const TOKEN_KEY = 'omnius_access_token';

export async function getStoredToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(TOKEN_KEY);
  } catch {
    return null;
  }
}

export async function setStoredToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(TOKEN_KEY, token);
}

export async function clearStoredToken(): Promise<void> {
  await SecureStore.deleteItemAsync(TOKEN_KEY);
}

export type ApiError = { status: number; message: string };

export async function apiFetch<T>(
  path: string,
  options: {
    method?: string;
    auth?: boolean;
    /** Use this token instead of reading from SecureStore (avoids race right after login). */
    authToken?: string | null;
    json?: unknown;
    form?: Record<string, string>;
    headers?: Record<string, string>;
  } = {}
): Promise<T> {
  const { method = 'GET', auth = true, authToken, json, form, headers = {} } = options;
  const url = `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;

  const h: Record<string, string> = { ...headers };
  let body: string | undefined;

  if (json !== undefined) {
    h['Content-Type'] = 'application/json';
    body = JSON.stringify(json);
  } else if (form !== undefined) {
    h['Content-Type'] = 'application/x-www-form-urlencoded';
    body = new URLSearchParams(form).toString();
  }

  if (auth) {
    const token = authToken !== undefined ? authToken : await getStoredToken();
    if (token) {
      h['Authorization'] = `Bearer ${token}`;
    }
  }

  const res = await fetch(url, { method, headers: h, body });
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const message =
      typeof data === 'object' && data !== null && 'detail' in data
        ? formatDetail((data as { detail: unknown }).detail)
        : typeof data === 'string'
          ? data
          : res.statusText;
    const err: ApiError = { status: res.status, message };
    throw err;
  }

  return data as T;
}

function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((x) => (typeof x === 'object' && x && 'msg' in x ? String((x as { msg: unknown }).msg) : JSON.stringify(x))).join('; ');
  }
  return JSON.stringify(detail);
}
