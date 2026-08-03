import { FC, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, CheckCircle2, Clock, Loader2, Package, Phone, Play, Square, Wrench,
} from 'lucide-react'
import { shopFloorApi, Fanout, Posting } from '../api/shopFloor'
import { Button } from '../components/ui'

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
    <div className="mt-3 rounded-md border border-gray-200 bg-white p-3">
      <div className="flex items-center gap-2">
        {fanout.fullyPosted ? (
          <CheckCircle2 className="h-4 w-4 text-green-600" />
        ) : (
          <Clock className="h-4 w-4 text-blue-600" />
        )}
        <p className="text-sm font-medium text-gray-900">{title}</p>
      </div>
      <ul className="mt-2 space-y-1 text-xs">
        {Object.entries(fanout.byStatus).map(([status, count]) => (
          <li key={status} className="text-gray-700">
            {count} {STATUS_LABEL[status] ?? status}
          </li>
        ))}
      </ul>
      {fanout.awaitingAPerson.length > 0 && (
        <div className="mt-2 rounded border border-amber-300 bg-amber-50 p-2">
          <p className="flex items-center gap-1.5 text-xs font-medium text-amber-900">
            <Phone className="h-3.5 w-3.5" />
            Someone has to be told:
          </p>
          <ul className="mt-1 space-y-1.5">
            {fanout.awaitingAPerson.map((item) => (
              <li key={item.target} className="text-xs text-amber-900">
                <span className="font-medium capitalize">{item.target}</span> —{' '}
                {item.instruction}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[11px] text-amber-800">
            Clear these on the ledger below once you have passed them on.
          </p>
        </div>
      )}
    </div>
  )
}

const Field: FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <label className="block">
    <span className="mb-1 block text-xs font-medium text-gray-700">{label}</span>
    {children}
  </label>
)

const inputClass =
  'w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm focus:border-blue-500 focus:outline-none'

const Card: FC<{ title: string; icon: React.ReactNode; routes: string; children: React.ReactNode }> = ({
  title,
  icon,
  routes,
  children,
}) => (
  <section className="rounded-lg border border-gray-200 bg-gray-50 p-4">
    <div className="mb-1 flex items-center gap-2">
      {icon}
      <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
    </div>
    {/* The mandate, stated on the page. An operator should be able to see where their
        action goes without reading a document. */}
    <p className="mb-3 text-[11px] text-gray-600">Goes to: {routes}</p>
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
      icon={<Package className="h-4 w-4 text-gray-700" />}
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
        <p className="mt-2 text-xs text-red-700" role="alert">
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
  const { data: open, isLoading } = useQuery({
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
      icon={<Clock className="h-4 w-4 text-gray-700" />}
      routes="production, accounting"
    >
      {isLoading ? (
        <p className="text-xs text-gray-500">Checking for a running clock…</p>
      ) : open ? (
        <div>
          <p className="text-sm text-gray-900">
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
            <p className="mt-2 text-xs text-red-700" role="alert">
              Could not clock out — YOUR CLOCK IS STILL RUNNING and no hours were posted.
              Try again; do not leave the floor assuming this was recorded.
            </p>
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
            <p className="mt-2 text-xs text-red-700" role="alert">
              Could not clock in. If you already have a clock running, close that one first —
              two open clocks produce overlapping hours and payroll cannot tell which is real.
            </p>
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
      icon={<AlertTriangle className="h-4 w-4 text-gray-700" />}
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
        <p className="mt-2 text-xs text-red-700" role="alert">
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
  const [openEventId, setOpenEventId] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const start = useMutation({
    mutationFn: () =>
      shopFloorApi.startDowntime({ assetId, downtimeType, reasonCode: reasonCode || undefined }),
    onSuccess: (event) => setOpenEventId(event.id),
  })
  const end = useMutation({
    mutationFn: (eventId: string) => shopFloorApi.endDowntime(eventId),
    onSuccess: () => {
      setOpenEventId(null)
      queryClient.invalidateQueries({ queryKey: ['shop-floor-postings'] })
    },
  })

  return (
    <Card
      title="Machine down"
      icon={<Wrench className="h-4 w-4 text-gray-700" />}
      routes="scheduling, production, quality, accounting"
    >
      {openEventId ? (
        <div>
          <p className="text-sm text-gray-900">
            Downtime is running. Nothing has been posted yet —{' '}
            {/* Said explicitly: scheduling and accounting need a DURATION, which does not
                exist until the machine is back up. Claiming a posting now would put an
                open-ended stop into a cost system. */}
            the duration scheduling and accounting need does not exist until it ends.
          </p>
          <Button className="mt-2" size="sm" onClick={() => end.mutate(openEventId)} disabled={end.isPending}>
            {end.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
            Machine is back up
          </Button>
          {end.isError && (
            <p className="mt-2 text-xs text-red-700" role="alert">
              Could not close this downtime — the machine is still recorded as down and
              scheduling has not been told it is back.
            </p>
          )}
        </div>
      ) : (
        <div>
          <div className="grid grid-cols-3 gap-2">
            <Field label="Asset id">
              <input className={inputClass} value={assetId} onChange={(e) => setAssetId(e.target.value)} />
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
            <p className="mt-2 text-xs text-red-700" role="alert">
              Downtime was NOT recorded — nothing is logged against this asset.
            </p>
          )}
        </div>
      )}
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
    <tr className="border-b border-gray-100 align-top">
      <td className="py-2 pr-3 text-sm capitalize text-gray-900">{posting.targetSystem}</td>
      <td className="py-2 pr-3 text-sm text-gray-700">{STATUS_LABEL[posting.status] ?? posting.status}</td>
      <td className="py-2 pr-3 text-xs text-gray-700">
        {posting.instruction || posting.lastError || '—'}
      </td>
      <td className="py-2 pr-3 font-mono text-xs text-gray-700">{posting.externalRef ?? '—'}</td>
      <td className="py-2">
        {needsAPerson ? (
          <div className="flex items-center gap-1.5">
            <input
              value={ref}
              onChange={(e) => setRef(e.target.value)}
              placeholder="their reference"
              className="w-32 rounded border border-gray-300 px-1.5 py-1 text-xs"
            />
            <Button size="sm" variant="outline" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
              I told them
            </Button>
          </div>
        ) : posting.acknowledgedAt ? (
          <span className="text-xs text-gray-500">handed over</span>
        ) : (
          <span className="text-xs text-gray-400">—</span>
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

  if (isLoading) return <p className="text-sm text-gray-500">Loading the ledger…</p>
  if (isError) {
    // An empty table here would read as "nothing outstanding", which is the opposite of
    // what a failed load means.
    return (
      <div role="alert" className="flex items-center gap-3">
        <p className="text-sm text-red-700">
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
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={outstandingOnly}
            onChange={(e) => setOutstandingOnly(e.target.checked)}
          />
          Only what still needs doing
        </label>
        <p className="text-xs text-gray-600">
          {data!.total} total
          {data!.truncated ? ` — showing the first ${data!.items.length}` : ''}
        </p>
      </div>
      {data!.items.length === 0 ? (
        <p className="text-sm text-gray-600">
          {outstandingOnly ? 'Nothing outstanding.' : 'No postings yet.'}
        </p>
      ) : (
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-200 text-left text-xs font-medium text-gray-600">
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
      <h1 className="text-xl font-semibold text-gray-900">Shop Floor</h1>
      <p className="mt-1 text-sm text-gray-600">
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

    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="mb-1 text-sm font-semibold text-gray-900">Systems of record</h2>
      <p className="mb-3 text-[11px] text-gray-600">
        One row per (event, system). A posting is only <span className="font-medium">posted</span>{' '}
        when the far system returned an identifier — that reference is the evidence.
      </p>
      <Ledger />
    </section>
  </div>
)

export default ShopFloor
