import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the digital-twin optimiser client (FS-488).
 *
 * One call, and the strictest wire in the codebase: the backend's `OptimizeRequest` is
 * declared `extra="forbid"`, so a single unrecognised key is a **422 for the whole request**.
 * The client's body is camelCase (`minImprovementPercent`, `emitRecommendations`) and the
 * schema is snake_case, which means every field would be unrecognised without the
 * `registerTransform('/api/v1/twin')` at module load.
 *
 * That line is one statement, has no callers, and nothing type-checks it. Delete it and every
 * optimisation request 422s — with no compile error, and no unit-test failure anywhere,
 * because the mock branch computes a response from the camelCase object and agrees with
 * itself. `extra="forbid"` at least makes the failure loud; the silent version of this is
 * `extra="ignore"`, where the run simply uses defaults for everything the caller asked for.
 *
 * So the registration is what this file asserts first. These tests mock `./client`, which
 * replaces axios and its interceptors, so the body seen here is pre-transform — asserting the
 * registration is the honest check at this layer, and the rename has its own tests in
 * `transformRegistry.test.ts`.
 */

const post = vi.fn()
const registerTransform = vi.fn()

vi.mock('./client', () => ({
  api: {
    post: (...args: unknown[]) => post(...args),
    get: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))
vi.mock('./transformRegistry', () => ({
  registerTransform: (...args: unknown[]) => registerTransform(...args),
}))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function twin(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./twinOptimizer'))
  return (mod as unknown as { twinOptimizerApi: AnyApi }).twinOptimizerApi
}

const REQUEST = {
  candidates: [{ type: 'parameter_tuning', overrides: { cycleTimeSeconds: 42 } }],
  runs: 200,
  minImprovementPercent: 2,
  emitRecommendations: false,
}

const RESPONSE = {
  recommendations: [],
  baseline: { oee: 0.71 },
  runs: 200,
  seed: 7,
}

beforeEach(() => {
  post.mockReset()
  registerTransform.mockReset()
  post.mockResolvedValue({ data: RESPONSE })
})

afterEach(() => {
  restoreMockMode()
})

describe('the camel-to-snake registration is load-bearing', () => {
  it('registers the twin prefix on import', async () => {
    // `OptimizeRequest` is `extra="forbid"`. Without this line every key in the body is
    // unrecognised and the whole request is a 422 — no compile error, no failing unit test.
    await twin()

    expect(registerTransform).toHaveBeenCalledWith('/api/v1/twin')
  })
})

describe('the optimisation request', () => {
  it('posts the body it was handed, unaltered', async () => {
    // The client adds nothing and drops nothing. With `extra="forbid"` on the other side,
    // a helpfully-injected default here would reject the entire run.
    const api = await twin()

    await api.optimize(REQUEST)

    expect(post).toHaveBeenCalledWith('/api/v1/twin/optimize', REQUEST)
  })

  it('returns the server response rather than a computed one', async () => {
    // The mock branch SYNTHESISES recommendations from the request. A real path that fell
    // back to that would present locally-invented advice as the twin's output.
    const api = await twin()

    expect(await api.optimize(REQUEST)).toEqual(RESPONSE)
  })

  it('lets a rejected request reach the caller', async () => {
    // A 422 from `extra="forbid"` has to surface: the run did not happen, and the page must
    // not show the previous result as though it had.
    post.mockRejectedValue(new Error('422'))
    const api = await twin()

    await expect(api.optimize(REQUEST)).rejects.toThrow()
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    const api = await twin()

    await api.optimize(REQUEST)

    expect(post).toHaveBeenCalled()
  })
})
