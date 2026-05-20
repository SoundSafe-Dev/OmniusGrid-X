import { USE_DEMO_DATA } from '../config';

/**
 * When true, data APIs hit the real backend even though the demo layer is enabled.
 * Used for `dev` / dev-token only when EXPO_PUBLIC_USE_DEMO_DATA=false (live DB parity with web).
 */
let forceLiveApi = false;

export function setForceLiveApiData(v: boolean) {
  forceLiveApi = v;
}

export function isForceLiveApiData(): boolean {
  return forceLiveApi;
}

/** True when in-memory demo dataset should intercept omniusApi (not login/me). */
export function useDemoDataLayer(): boolean {
  return USE_DEMO_DATA && !forceLiveApi;
}
