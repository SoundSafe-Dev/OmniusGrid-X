/**
 * The cloud gateway page, which used to answer a question nobody could ask.
 *
 * `/cloud/status` returns four fields. On a failed query `data` is undefined, and this
 * page rendered its error banner and then went on to state, in full sentences under
 * coloured icons:
 *
 *     Disconnected · Offline · Queue Depth 0 items · mTLS Disabled
 *     "Mutual TLS is not enabled on this gateway connection."
 *
 * All four came out of `undefined` — via `|| false`, `?? 0`, and ternaries whose falsy
 * branch is an assertion rather than a blank. Two of them matter operationally:
 *
 *   **Queue Depth 0** says nothing is stranded at the edge. That is precisely what an
 *   operator checks after an outage, and it is the reading that stops them looking.
 *
 *   **mTLS Disabled** is a security finding about a link that was never inspected. It is
 *   printed beside a red shield with a sentence explaining the consequence.
 *
 * A failed status query means the STATUS is unreadable. It does not mean the gateway is
 * down, its queue is empty, or its encryption is off — the gateway may be perfectly
 * healthy while the endpoint that describes it is not.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getCloudGatewayStatus = vi.fn()
const forceCloudFlush = vi.fn()

vi.mock('../../api', () => ({
  enginesApi: {
    getCloudGatewayStatus: (...a: unknown[]) => getCloudGatewayStatus(...a),
    forceCloudFlush: (...a: unknown[]) => forceCloudFlush(...a),
  },
}))

import { TooltipProvider } from '../../components/ui'
import { CloudGateway } from './CloudGateway'

// Shape from the CloudStatus interface the page declares against the real endpoint —
// connection flag, queue size, endpoint host, mTLS flag. Nothing else is sent.
const status = (over: Record<string, unknown> = {}) => ({
  connected: true,
  queueSize: 12,
  endpoint: 'ingest.omniusgrid.example',
  mtlsEnabled: true,
  ...over,
})

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <CloudGateway />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getCloudGatewayStatus.mockResolvedValue(status())
  forceCloudFlush.mockResolvedValue({ flushed: 12 })
})

describe('CloudGateway — a healthy gateway', () => {
  it('reports what the gateway actually said', async () => {
    // The positive control for everything below. Without it, "does not say Disconnected"
    // is satisfied by a page that never says Connected either.
    wrap()
    expect(await screen.findByText('Connected')).toBeInTheDocument()
    expect(screen.getByText('12 items')).toBeInTheDocument()
    expect(screen.getByText('mTLS Enabled')).toBeInTheDocument()
    expect(screen.getByText(/Endpoint: ingest\.omniusgrid\.example/)).toBeInTheDocument()
  })

  it('still reports a genuine disconnection as a disconnection', async () => {
    // The other direction, and the one that keeps the fix honest: routing everything
    // through "unknown" would satisfy every assertion below and destroy the page.
    getCloudGatewayStatus.mockResolvedValue(
      status({ connected: false, queueSize: 0, mtlsEnabled: false }),
    )
    wrap()
    expect(await screen.findByText('Disconnected')).toBeInTheDocument()
    expect(screen.getByText('0 items')).toBeInTheDocument()
    expect(screen.getByText('mTLS Disabled')).toBeInTheDocument()
    expect(
      screen.getByText('Mutual TLS is not enabled on this gateway connection.'),
    ).toBeInTheDocument()
  })
})

describe('CloudGateway — a failed status query is not a status', () => {
  const failing = () => getCloudGatewayStatus.mockRejectedValue(new Error('unreachable'))

  it('does not report the gateway as disconnected', async () => {
    failing()
    wrap()
    expect(await screen.findByText('Status unknown')).toBeInTheDocument()
    expect(screen.queryByText('Disconnected')).not.toBeInTheDocument()
    expect(screen.queryByText('Offline')).not.toBeInTheDocument()
  })

  it('does not report an empty queue', async () => {
    // THE OPERATIONAL ONE. "0 items" reads as "nothing is stranded at the edge", which
    // is exactly the check someone runs after an outage.
    failing()
    wrap()
    await screen.findByText('Status unknown')
    expect(screen.queryByText('0 items')).not.toBeInTheDocument()
    expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0)
  })

  it('does not report mTLS as disabled', async () => {
    // THE SECURITY ONE. A red shield and a sentence saying the link is unencrypted,
    // concluded from a request that never returned.
    failing()
    wrap()
    await screen.findByText('Status unknown')
    expect(screen.queryByText('mTLS Disabled')).not.toBeInTheDocument()
    expect(
      screen.queryByText('Mutual TLS is not enabled on this gateway connection.'),
    ).not.toBeInTheDocument()
    expect(screen.getByText('mTLS state unknown')).toBeInTheDocument()
  })

  it('says plainly that the unknown state is not a finding', async () => {
    // A blank "—" beside a security heading still reads as reassurance. The wording has
    // to refuse the inference rather than merely withhold the claim.
    failing()
    wrap()
    const explanation = await screen.findByText(
      /encryption state is unknown\. This is not a finding that mTLS is disabled/i,
    )
    expect(explanation).toBeInTheDocument()
  })

  it('still shows that the request failed', async () => {
    failing()
    wrap()
    expect(
      await screen.findByText(/Failed to load gateway status/i),
    ).toBeInTheDocument()
  })

  it('does not offer a flush it cannot know the gateway can accept', async () => {
    // NOT ONE OF THE FOUR DEFECTS. The button was already disabled here, because
    // `!isConnected` happens to be true when the status is unknown. The gate now names
    // the real reason (`!known ||`) so it survives `isConnected` changing meaning, and
    // this pins the behaviour — it does not record a bug that existed.
    failing()
    wrap()
    await screen.findByText('Status unknown')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /flush now/i })).toBeDisabled(),
    )
    expect(forceCloudFlush).not.toHaveBeenCalled()
  })
})
