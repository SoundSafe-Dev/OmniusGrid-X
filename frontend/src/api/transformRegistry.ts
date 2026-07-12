/**
 * Prefix-gated casing seam (FS-60).
 *
 * Convention: the wire speaks snake_case (FastAPI default), TypeScript speaks
 * camelCase, and conversion happens HERE — once, on the shared axios instance
 * — instead of ~54 per-call toCamel/toSnake wraps spread across clients.
 *
 * Registration is OPT-IN by URL prefix. A blanket interceptor was rejected
 * deliberately:
 *  - several backends already emit camelCase (fleet_health, fleet_logistics,
 *    parts of transportation/auth) — legacy-camel, converge only with
 *    mobile-consumer coordination;
 *  - other clients consume snake_case as-is (nlp/user/feature-flags — other
 *    devs' lanes) and Record<string, …> maps keyed by metric names would be
 *    corrupted by an unscoped toCamel.
 *
 * NEVER register: /api/v1/nlp, /api/v1/user, /api/v1/feature-flags,
 * /api/v1/auth, /api/v1/fleet, /api/v1/geofencing, /api/v1/maintenance,
 * /api/v1/logistics.
 */
import type { InternalAxiosRequestConfig, AxiosResponse } from 'axios';
import { toCamel, toSnake } from './transform';

interface TransformEntry {
  /** wire->TS field-name aliases beyond casing (e.g. carrier_name -> name) */
  inAliases?: Record<string, string>;
  /** TS->wire aliases (inverse direction) */
  outAliases?: Record<string, string>;
}

const registry = new Map<string, TransformEntry>();

export function registerTransform(prefix: string, entry: TransformEntry = {}): void {
  registry.set(prefix, entry);
}

function entryFor(url: string | undefined): TransformEntry | undefined {
  if (!url) return undefined;
  // axios urls here are relative ('/api/v1/...') — match on pathname
  const path = url.startsWith('http') ? new URL(url).pathname : url;
  for (const [prefix, entry] of registry) {
    if (path === prefix || path.startsWith(prefix.endsWith('/') ? prefix : prefix + '/')
        || path.startsWith(prefix + '?')) {
      return entry;
    }
  }
  return undefined;
}

function isTransformableBody(data: unknown): data is object {
  if (data === null || typeof data !== 'object') return false;
  if (typeof FormData !== 'undefined' && data instanceof FormData) return false;
  if (typeof Blob !== 'undefined' && data instanceof Blob) return false;
  if (typeof URLSearchParams !== 'undefined' && data instanceof URLSearchParams) return false;
  if (data instanceof ArrayBuffer) return false;
  return true;
}

export function requestTransform(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  const entry = entryFor(config.url);
  if (!entry) return config;
  if (isTransformableBody(config.data)) {
    config.data = toSnake(config.data, entry.outAliases ?? {});
  }
  if (config.params && isTransformableBody(config.params)) {
    config.params = toSnake(config.params, entry.outAliases ?? {});
  }
  return config;
}

export function responseTransform(response: AxiosResponse): AxiosResponse {
  const entry = entryFor(response.config?.url);
  if (!entry) return response;
  const type = response.config?.responseType;
  if (type === 'blob' || type === 'arraybuffer') return response;
  if (response.data !== null && typeof response.data === 'object') {
    response.data = toCamel(response.data, entry.inAliases ?? {});
  }
  return response;
}
