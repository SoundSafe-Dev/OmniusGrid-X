/**
 * The login page — the entry point to everything, and untested until now.
 *
 * Two properties matter more than the rest, and neither is visible by clicking around:
 *
 * **The dev bypass must stay off.** `DEV_MODE` is `import.meta.env.DEV &&
 * VITE_DEV_MODE === 'true'`, so a production bundle cannot enable it. If that guard is
 * ever loosened to `VITE_DEV_MODE === 'true'` alone, typing `dev` in the username box
 * signs anyone in as an admin of the seeded demo organisation with a hardcoded token —
 * and nothing on screen would look different. The test asserts the compiled behaviour
 * rather than reading the source, so a change to the expression fails here.
 *
 * **A failed login must not navigate.** `login()` rejects and the store holds the error;
 * the `catch` is empty by design ("Error is handled by the auth store"). If the
 * `navigate` call ever escapes the `try`, a wrong password lands on the dashboard with
 * no session — which reads as a broken app, not a rejected credential.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigate,
    useLocation: () => ({ state: null, pathname: '/login' }),
  }
})

const login = vi.fn()
const devLogin = vi.fn()
const clearError = vi.fn()
let storeState: Record<string, unknown> = {}

vi.mock('../../stores', () => ({
  useAuthStore: () => ({
    login,
    devLogin,
    clearError,
    isLoading: false,
    error: null,
    ...storeState,
  }),
}))

// The page's tooltips are Radix primitives and need their provider; without it the
// component throws during render and every assertion below fails on an empty document.
import { TooltipProvider } from '../../components/ui'
import { Login } from './Login'

const wrap = () =>
  render(
    <TooltipProvider>
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    </TooltipProvider>,
  )

const submit = (user: string, pass = 'hunter2') => {
  fireEvent.change(screen.getByLabelText(/email|username/i), { target: { value: user } })
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: pass } })
  fireEvent.click(screen.getByRole('button', { name: /sign in|log in/i }))
}

beforeEach(() => {
  vi.clearAllMocks()
  storeState = {}
  login.mockResolvedValue(undefined)
})

describe('Login', () => {
  it('renders the form', () => {
    wrap()
    expect(screen.getByLabelText(/email|username/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in|log in/i })).toBeInTheDocument()
  })

  it('signs in with what was typed', async () => {
    wrap()
    submit('operator@example.test')
    await waitFor(() =>
      expect(login).toHaveBeenCalledWith(
        expect.objectContaining({ email: 'operator@example.test', password: 'hunter2' }),
      ),
    )
  })

  it('navigates once the credentials are accepted', async () => {
    wrap()
    submit('operator@example.test')
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/', { replace: true }))
  })

  it('surfaces the store error', () => {
    storeState = { error: 'Invalid email or password' }
    wrap()
    expect(screen.getByText('Invalid email or password')).toBeInTheDocument()
  })
})

describe('Login — a rejected credential goes nowhere', () => {
  it('does not navigate when login fails', async () => {
    // The `catch` is empty on purpose; what must not happen is the navigate escaping
    // the `try`. A wrong password landing on the dashboard with no session reads as a
    // broken application rather than a refused login.
    login.mockRejectedValue(new Error('401'))
    wrap()
    submit('operator@example.test', 'wrong')
    await waitFor(() => expect(login).toHaveBeenCalled())
    expect(navigate).not.toHaveBeenCalled()
  })

  it('clears any previous error before trying again', async () => {
    wrap()
    submit('operator@example.test')
    await waitFor(() => expect(clearError).toHaveBeenCalled())
  })
})

describe('Login — the dev bypass', () => {
  it('is off in this build, so "dev" is treated as an ordinary username', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. `DEV_MODE` is `import.meta.env.DEV &&
    // VITE_DEV_MODE === 'true'`; the second half is unset here, so the bypass must not
    // fire. Loosening that expression would sign anyone in as an admin of the seeded
    // demo organisation on a hardcoded token, and nothing on screen would differ.
    wrap()
    submit('dev')
    await waitFor(() => expect(login).toHaveBeenCalled())
    expect(devLogin).not.toHaveBeenCalled()
  })

  it('DOES fire when the flag is set, so the check above is not vacuous', async () => {
    // Without this, "devLogin was not called" is satisfied just as well by a bypass
    // that no longer exists — and the assertion above would keep passing after the
    // mechanism had been deleted or broken, telling nobody anything.
    //
    // `DEV_MODE` is read at module load, so the flag has to be set before a fresh
    // import. Under vitest `import.meta.env.DEV` is already true, which is exactly the
    // half of the condition a production bundle can never satisfy.
    vi.stubEnv('VITE_DEV_MODE', 'true')
    vi.resetModules()
    try {
      const { Login: DevLogin } = await import('./Login')
      render(
        <TooltipProvider>
          <MemoryRouter>
            <DevLogin />
          </MemoryRouter>
        </TooltipProvider>,
      )
      submit('dev')
      await waitFor(() => expect(devLogin).toHaveBeenCalled())
      expect(login).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllEnvs()
      vi.resetModules()
    }
  })

  it('is not reachable by capitalisation either', async () => {
    // The bypass lowercases and trims before comparing, so "DEV " would hit it if it
    // were enabled. Pinned so the guard above cannot be sidestepped by input shape.
    wrap()
    submit('  DEV ')
    await waitFor(() => expect(login).toHaveBeenCalled())
    expect(devLogin).not.toHaveBeenCalled()
  })
})

describe('Login — password visibility', () => {
  it('starts masked and can be revealed', () => {
    // Selected structurally, not by accessible name, because the toggle HAS none: it is
    // an icon-only <button> whose meaning lives in a tooltip, which Radix exposes as a
    // description rather than a name. A screen-reader user hears "button".
    //
    // Deliberately NOT fixed here — the htmlFor/aria-label sweep is another lane's first
    // ticket, and quietly doing one instance of it would take the work and leave the
    // pattern. Recorded in docs/engineering/defect-class-sweeps.md instead.
    const { container } = wrap()
    expect(screen.getByLabelText(/password/i)).toHaveAttribute('type', 'password')
    const toggle = container.querySelector('button[type="button"]')
    expect(toggle).toBeTruthy()
    fireEvent.click(toggle!)
    expect(screen.getByLabelText(/password/i)).toHaveAttribute('type', 'text')
  })
})
