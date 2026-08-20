import { FC, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, CheckCircle2, Clock, Loader2, Package, Phone, Play, Square, Wrench,
} from 'lucide-react'
import { shopFloorApi, Fanout, Posting } from '../api/shopFloor'
import { assetsApi } from '../api'
import { formatDateTime } from '../utils/formatters'
import { Button, ErrorState } from '../components/ui'

/**
 * The four floor workflows, and the ledger of what each one reached (FS-405).
 *
 *     issue a part      -> inventory, purchasing, accounting
 *     clock time        -> production, accounting
 *     report a problem  -> quality, inventory, production, accounting
 *     log downtime      -> scheduling, production, quality, accounting
 *
 * WHY THE RESULT PANEL IS AS BIG AS THE FORMS. Recording the event is the easy half. The
 * half that matters — and the half this platform had no way to express until now — is
 * whether each of those systems actually heard about it. A "Saved ✓" toast on a shop with no
 * purchasing integration would be a lie by omission: the part left the shelf, and nobody
 * ordered another.
 *
 * So every submission renders its fan-out per target, and any target with no integration
 * shows the sentence to hand to a person, with a control to record that it was handed over.
 */

const STATUS_LABEL: Record<string, string> = {
  pending: 'queued',
  posted: 'posted',
  failed: 'failed',
  manual_required: 'needs a person',
  not_applicable: 'not routed here',
}

/** The per-target breakdown. Never collapsed into one line. */
const FanoutPanel: FC<{ fanout: Fanout | null; title: string }> = ({ fanout, title }) => {
  if (!fanout) return null
  return (
    <div className="mt-3 rounded-md border border-opsgrid-border bg-opsgrid-bg p-3">
      <div className="flex items-center gap-2">
        {fanout.fullyPosted ? (
          <CheckCircle2 className="h-4 w-4 text-green-600" />
        ) : (
          <Clock className="h-4 w-4 text-blue-600" />
        )}
        <p className="text-sm font-medium text-opsgrid-text">{title}</p>
      </div>
      <ul className="mt-2 space-y-1 text-xs">
        {Object.entries(fanout.byStatus).map(([status, count]) => (
          <li key={status} className="text-opsgrid-text-secondary">
            {count} {STATUS_LABEL[status] ?? status}
          </li>
        ))}
      </ul>
      {fanout.awaitingAPerson.length > 0 && (
        <div className="mt-2 rounded border border-status-warning/50 bg-status-warning/10 p-2">
          <p className="flex items-center gap-1.5 text-xs font-medium text-status-warning">
            <Phone className="h-3.5 w-3.5" />
            Someone has to be told:
          </p>
          <ul className="mt-1 space-y-1.5">
            {fanout.awaitingAPerson.map((item) => (
              <li key={item.target} className="text-xs text-opsgrid-text">
                <span className="font-medium capitalize">{item.target}</span> —{' '}
                {item.instruction}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[11px] text-opsgrid-text-secondary">
            Clear these on the ledger below once you have passed them on.
          </p>
        </div>
      )}
    </div>
  )
}

const Field: FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <label className="block">
    <span className="mb-1 block text-xs font-medium text-opsgrid-text-secondary">{label}</span>
    {children}
  </label>
)

const inputClass =
  'w-full rounded border border-opsgrid-border bg-opsgrid-bg px-2.5 py-1.5 text-sm '  +
  'text-opsgrid-text placeholder:text-opsgrid-text-secondary focus:border-opsgrid-primary focus:outline-none'

const Card: FC<{ title: string; icon: React.ReactNode; routes: string; children: React.ReactNode }> = ({
  title,
  icon,
  routes,
  children,
}) => (
  <section className="rounded-lg border border-opsgrid-border bg-opsgrid-panel p-4">
    <div className="mb-1 flex items-center gap-2">
      {icon}
      <h2 className="text-sm font-semibold text-opsgrid-text">{title}</h2>
    </div>
    {/* The mandate, stated on the page. An operator should be able to see where their
        action goes without reading a document. */}
    <p className="mb-3 text-[11px] text-opsgrid-text-secondary">Goes to: {routes}</p>
    {children}
  </section>
)

const IssuePart: FC = () => {
  const [partNumber, setPartNumber] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [workOrderRef, setWorkOrderRef] = useState('')
  const [unitCost, setUnitCost] = useState('')
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () =>
      shopFloorApi.issuePart({
        partNumber,
        quantity: Number(quantity),
        workOrderRef: workOrderRef || undefined,
        // Sent only when entered. An empty box means "not priced yet", which is a
        // different statement to an accounting system than "free".
        unitCost: unitCost ? Number(unitCost) : undefined,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shop-floor-postings'] }),
  })

  return (
    <Card
      title="Issue a part"
      icon={<Package className="h-4 w-4 text-opsgrid-text-secondary" />}
      routes="inventory, purchasing, accounting"
    >
      <div className="grid grid-cols-2 gap-2">
        <Field label="Part number">
          <input className={inputClass} value={partNumber} onChange={(e) => setPartNumber(e.target.value)} />
        </Field>
        <Field label="Quantity">
          <input className={inputClass} type="number" min="0" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </Field>
        <Field label="Work order (optional)">
          <input className={inputClass} value={workOrderRef} onChange={(e) => setWorkOrderRef(e.target.value)} />
        </Field>
        <Field label="Unit cost (optional)">
          <input className={inputClass} type="number" min="0" step="any" value={unitCost} onChange={(e) => setUnitCost(e.target.value)} />
        </Field>
      </div>
      <Button
        className="mt-3"
        size="sm"
        onClick={() => mutation.mutate()}
        disabled={!partNumber || !quantity || mutation.isPending}
      >
        {mutation.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
        Issue part
      </Button>
      {mutation.isError && (
        <p className="mt-2 text-xs text-status-alarm" role="alert">
          The part was NOT issued — nothing was recorded and no system was told.
        </p>
      )}
      <FanoutPanel
        fanout={mutation.data?.fanout ?? null}
        title={`${mutation.data?.quantity ?? ''} ${mutation.data?.partNumber ?? ''} issued`}
      />
    </Card>
  )
}

const ClockTime: FC = () => {
  const queryClient = useQueryClient()
  // `isError` is read because the failure defaults into the DANGEROUS branch (FS-482).
  // On a failed lookup `open` is undefined and `isLoading` is false, which is exactly the
  // shape of "no clock is running" — so the card offered "Clock in" to somebody who may
  // already be clocked in, producing the two open clocks the message below that button
  // warns about. Absence of an answer is not the answer "no".
  const { data: open, isLoading, isError, refetch } = useQuery({
    queryKey: ['shop-floor-open-labor'],
    queryFn: () => shopFloorApi.openLaborEntry(),
  })
  const [workOrderRef, setWorkOrderRef] = useState('')

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['shop-floor-open-labor'] })
    queryClient.invalidateQueries({ queryKey: ['shop-floor-postings'] })
  }

  const clockIn = useMutation({
    mutationFn: () => shopFloorApi.clockIn({ workOrderRef: workOrderRef || undefined }),
    onSuccess: invalidate,
  })
  const clockOut = useMutation({
    mutationFn: () => shopFloorApi.clockOut(),
    onSuccess: invalidate,
  })

  return (
    <Card
      title="Clock time"
      icon={<Clock className="h-4 w-4 text-opsgrid-text-secondary" />}
      routes="production, accounting"
    >
      {isLoading ? (
        <p className="text-xs text-opsgrid-text-secondary">Checking for a running clock…</p>
      ) : isError ? (
        <div>
          <ErrorState message="Could not check whether you already have a clock running. Neither button is shown, because clocking in on top of an open clock produces overlapping hours that payroll cannot reconcile." />
          <Button className="mt-2" size="sm" variant="outline" onClick={() => refetch()}>
            Check again
          </Button>
        </div>
      ) : open ? (
        <div>
          <p className="text-sm text-opsgrid-text">
            Clocked in since {new Date(open.clockInAt).toLocaleTimeString()}
            {open.workOrderRef ? ` on ${open.workOrderRef}` : ''}
          </p>
          {/* Deliberately NOT showing an elapsed-hours figure that will be posted: the
              duration is computed server-side at clock-out, and a client-side estimate
              shown next to a payroll claim would be a number nobody can reconcile. */}
          <Button className="mt-2" size="sm" onClick={() => clockOut.mutate()} disabled={clockOut.isPending}>
            {clockOut.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Square className="mr-1 h-3.5 w-3.5" />}
            Clock out
          </Button>
          {clockOut.isError && (
            <ErrorState message="Could not clock out — YOUR CLOCK IS STILL RUNNING and no hours were posted. Try again; do not leave the floor assuming this was recorded." />
          )}
        </div>
      ) : (
        <div>
          <Field label="Work order (optional)">
            <input className={inputClass} value={workOrderRef} onChange={(e) => setWorkOrderRef(e.target.value)} />
          </Field>
          <Button className="mt-2" size="sm" onClick={() => clockIn.mutate()} disabled={clockIn.isPending}>
            {clockIn.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1 h-3.5 w-3.5" />}
            Clock in
          </Button>
          {clockIn.isError && (
            <ErrorState message="Could not clock in. If you already have a clock running, close that one first — two open clocks produce overlapping hours and payroll cannot tell which is real." />
          )}
        </div>
      )}
      <FanoutPanel fanout={clockOut.data?.fanout ?? null} title="Hours recorded" />
    </Card>
  )
}

const ReportProblem: FC = () => {
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState('minor')
  const [partNumber, setPartNumber] = useState('')
  const [scrapQuantity, setScrapQuantity] = useState('')
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () =>
      shopFloorApi.reportProblem({
        description,
        severity,
        partNumber: partNumber || undefined,
        scrapQuantity: scrapQuantity ? Number(scrapQuantity) : undefined,
        quantityAffected: scrapQuantity ? Number(scrapQuantity) : undefined,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shop-floor-postings'] }),
  })

  return (
    <Card
      title="Report a problem"
      icon={<AlertTriangle className="h-4 w-4 text-opsgrid-text-secondary" />}
      routes="quality, inventory, production, accounting"
    >
      <Field label="What happened">
        <textarea className={inputClass} rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <div className="mt-2 grid grid-cols-3 gap-2">
        <Field label="Severity">
          <select className={inputClass} value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="minor">minor</option>
            <option value="major">major</option>
            <option value="critical">critical</option>
          </select>
        </Field>
        <Field label="Part (optional)">
          <input className={inputClass} value={partNumber} onChange={(e) => setPartNumber(e.target.value)} />
        </Field>
        <Field label="Scrapped (optional)">
          <input className={inputClass} type="number" min="0" step="any" value={scrapQuantity} onChange={(e) => setScrapQuantity(e.target.value)} />
        </Field>
      </div>
      <Button className="mt-3" size="sm" onClick={() => mutation.mutate()} disabled={!description || mutation.isPending}>
        {mutation.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
        Report it
      </Button>
      {mutation.isError && (
        <p className="mt-2 text-xs text-status-alarm" role="alert">
          Not recorded — no quality record was raised and nobody was told.
        </p>
      )}
      <FanoutPanel fanout={mutation.data?.fanout ?? null} title="Problem raised" />
    </Card>
  )
}

const MachineDown: FC = () => {
  const [assetId, setAssetId] = useState('')
  const [reasonCode, setReasonCode] = useState('')
  const [downtimeType, setDowntimeType] = useState('unplanned')
  const queryClient = useQueryClient()

  // The machines to pick from (P5). This card used to ask for a UUID in a free-text
  // box — unusable on a real floor, where nobody types 36 hex characters at a down
  // machine. The same list also names the assets in the open-downtime rows below.
  const { data: assetsPage } = useQuery({
    queryKey: ['shop-floor-assets'],
    queryFn: () => assetsApi.list({ limit: 200 }),
  })
  const assets = assetsPage?.items ?? []
  const assetName = (id: string) =>
    assets.find((asset: any) => asset.id === id)?.name ?? id

  // Open downtime from the SERVER, not component state (P5). The open event id used to
  // live in useState, so a reload stranded an in-progress downtime: the machine stayed
  // recorded as down, the operator who started it could not end it, and no other
  // operator could see it existed. The server is the truth about which machines are
  // down; any operator can close any of them.
  const openQuery = useQuery({
    queryKey: ['shop-floor-open-downtime'],
    queryFn: () => shopFloorApi.openDowntime(),
    refetchInterval: 30000,
  })
  const openEvents = openQuery.data ?? []

  const start = useMutation({
    mutationFn: () =>
      shopFloorApi.startDowntime({ assetId, downtimeType, reasonCode: reasonCode || undefined }),
    onSuccess: () => {
      setAssetId('')
      setReasonCode('')
      queryClient.invalidateQueries({ queryKey: ['shop-floor-open-downtime'] })
    },
  })
  const end = useMutation({
    mutationFn: (eventId: string) => shopFloorApi.endDowntime(eventId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shop-floor-open-downtime'] })
      queryClient.invalidateQueries({ queryKey: ['shop-floor-postings'] })
    },
  })

  return (
    <Card
      title="Machine down"
      icon={<Wrench className="h-4 w-4 text-opsgrid-text-secondary" />}
      routes="scheduling, production, quality, accounting"
    >
      {openQuery.isError && (
        <ErrorState message="Could not load open downtime — a machine may be recorded as down that is not shown here." />
      )}
      {openEvents.length > 0 && (
        <div className="mb-3 space-y-2">
          {openEvents.map((event) => (
            <div
              key={event.id}
              className="rounded border border-status-alarm/40 bg-status-alarm/10 px-3 py-2"
            >
              <p className="text-sm text-opsgrid-text">
                <span className="font-medium">{assetName(event.assetId)}</span> is down
                ({event.downtimeType}
                {event.reasonCode ? `, ${event.reasonCode}` : ''}) since{' '}
                {formatDateTime(event.startedAt)}.{' '}
                {/* Said explicitly: scheduling and accounting need a DURATION, which does
                    not exist until the machine is back up. Claiming a posting now would
                    put an open-ended stop into a cost system. */}
                Nothing posts until it ends.
              </p>
              <Button
                className="mt-2"
                size="sm"
                onClick={() => end.mutate(event.id)}
                disabled={end.isPending}
              >
                {end.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
                Machine is back up
              </Button>
            </div>
          ))}
          {end.isError && (
            <ErrorState message="Could not close this downtime — the machine is still recorded as down and scheduling has not been told it is back." />
          )}
        </div>
      )}
      <div>
        <div className="grid grid-cols-3 gap-2">
          <Field label="Asset">
            <select
              className={inputClass}
              value={assetId}
              onChange={(e) => setAssetId(e.target.value)}
              aria-label="Asset"
            >
              <option value="">Select a machine…</option>
              {assets.map((asset: any) => (
                <option key={asset.id} value={asset.id}>{asset.name}</option>
              ))}
            </select>
          </Field>
          <Field label="Type">
            <select className={inputClass} value={downtimeType} onChange={(e) => setDowntimeType(e.target.value)}>
              <option value="unplanned">unplanned</option>
              <option value="planned">planned</option>
              <option value="changeover">changeover</option>
            </select>
          </Field>
          <Field label="Reason (optional)">
            <input className={inputClass} value={reasonCode} onChange={(e) => setReasonCode(e.target.value)} />
          </Field>
        </div>
        <Button className="mt-3" size="sm" onClick={() => start.mutate()} disabled={!assetId || start.isPending}>
          {start.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
          Start downtime
        </Button>
        {start.isError && (
          <p className="mt-2 text-xs text-status-alarm" role="alert">
            Downtime was NOT recorded — nothing is logged against this asset.
          </p>
        )}
      </div>
      <FanoutPanel fanout={end.data?.fanout ?? null} title="Downtime closed" />
    </Card>
  )
}

const PostingRow: FC<{ posting: Posting }> = ({ posting }) => {
  const [ref, setRef] = useState('')
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => shopFloorApi.acknowledgePosting(posting.id, ref.trim() || undefined),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shop-floor-postings'] }),
  })

  const needsAPerson = posting.status === 'manual_required' && !posting.acknowledgedAt

  return (
    <tr className="border-b border-opsgrid-border align-top">
      <td className="py-2 pr-3 text-sm capitalize text-opsgrid-text">{posting.targetSystem}</td>
      <td className="py-2 pr-3 text-sm text-opsgrid-text-secondary">{STATUS_LABEL[posting.status] ?? posting.status}</td>
      <td className="py-2 pr-3 text-xs text-opsgrid-text-secondary">
        {posting.instruction || posting.lastError || '—'}
      </td>
      <td className="py-2 pr-3 font-mono text-xs text-opsgrid-text-secondary">{posting.externalRef ?? '—'}</td>
      <td className="py-2">
        {needsAPerson ? (
          <div className="flex items-center gap-1.5">
            <input
              value={ref}
              onChange={(e) => setRef(e.target.value)}
              placeholder="their reference"
              className="w-32 rounded border border-opsgrid-border bg-opsgrid-bg px-1.5 py-1 text-xs text-opsgrid-text placeholder:text-opsgrid-text-secondary"
            />
            <Button size="sm" variant="outline" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
              I told them
            </Button>
          </div>
        ) : posting.acknowledgedAt ? (
          <span className="text-xs text-opsgrid-text-secondary">handed over</span>
        ) : (
          <span className="text-xs text-opsgrid-text-secondary">—</span>
        )}
      </td>
    </tr>
  )
}

const Ledger: FC = () => {
  const [outstandingOnly, setOutstandingOnly] = useState(true)
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['shop-floor-postings', outstandingOnly],
    queryFn: () => shopFloorApi.listPostings({ outstandingOnly, limit: 100 }),
  })

  if (isLoading) return <p className="text-sm text-opsgrid-text-secondary">Loading the ledger…</p>
  if (isError) {
    // An empty table here would read as "nothing outstanding", which is the opposite of
    // what a failed load means.
    return (
      <div role="alert" className="flex items-center gap-3">
        <p className="text-sm text-status-alarm">
          Couldn’t load the ledger — this is a loading failure, not an empty backlog.
        </p>
        <Button size="sm" variant="outline" onClick={() => refetch()}>
          Retry
        </Button>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm text-opsgrid-text-secondary">
          <input
            type="checkbox"
            checked={outstandingOnly}
            onChange={(e) => setOutstandingOnly(e.target.checked)}
          />
          Only what still needs doing
        </label>
        <p className="text-xs text-opsgrid-text-secondary">
          {data!.total} total
          {data!.truncated ? ` — showing the first ${data!.items.length}` : ''}
        </p>
      </div>
      {data!.items.length === 0 ? (
        <p className="text-sm text-opsgrid-text-secondary">
          {outstandingOnly ? 'Nothing outstanding.' : 'No postings yet.'}
        </p>
      ) : (
        <table className="w-full">
          <thead>
            <tr className="border-b border-opsgrid-border text-left text-xs font-medium text-opsgrid-text-secondary">
              <th className="pb-2">System</th>
              <th className="pb-2">Status</th>
              <th className="pb-2">What to do / what went wrong</th>
              <th className="pb-2">Reference</th>
              <th className="pb-2" />
            </tr>
          </thead>
          <tbody>
            {data!.items.map((posting) => (
              <PostingRow key={posting.id} posting={posting} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

const ShopFloor: FC = () => (
  <div className="space-y-5 p-1">
    <header>
      <h1 className="text-xl font-semibold text-opsgrid-text">Shop Floor</h1>
      <p className="mt-1 text-sm text-opsgrid-text-secondary">
        Record what happened, and see exactly which systems heard about it. A target with no
        integration is handed to a person, with the words to use — not dropped.
      </p>
    </header>

    <div className="grid gap-4 lg:grid-cols-2">
      <IssuePart />
      <ClockTime />
      <ReportProblem />
      <MachineDown />
    </div>

    <section className="rounded-lg border border-opsgrid-border bg-opsgrid-panel p-4">
      <h2 className="mb-1 text-sm font-semibold text-opsgrid-text">Systems of record</h2>
      <p className="mb-3 text-[11px] text-opsgrid-text-secondary">
        One row per (event, system). A posting is only <span className="font-medium">posted</span>{' '}
        when the far system returned an identifier — that reference is the evidence.
      </p>
      <Ledger />
    </section>
  </div>
)

export default ShopFloor
