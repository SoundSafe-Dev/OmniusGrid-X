import { FC } from 'react'
import { DoorOpen, Truck } from 'lucide-react'
import { DockDoor, YardTrailer } from '../../types'

// Yard map (task C19): CSS-grid visualization of dock doors (live occupancy) and
// yard zones (trailers grouped by yardLocation). Pure over the doors/trailers
// the page already queries, so it works in both mock and real modes.

export function groupTrailersByZone(trailers: YardTrailer[]): Record<string, YardTrailer[]> {
  const zones: Record<string, YardTrailer[]> = {}
  for (const t of trailers) {
    if (t.status === 'outbound' || t.status === 'in_transit') continue
    const zone = t.assignedDoorId ? '__docked__' : (t.yardLocation || 'Unassigned')
    ;(zones[zone] ??= []).push(t)
  }
  delete zones.__docked__ // docked trailers render on their door instead
  return zones
}

const doorColor = (status: DockDoor['status']) =>
  status === 'available' ? 'border-status-running/60 bg-status-running/10'
  : status === 'occupied' ? 'border-opsgrid-primary bg-opsgrid-primary/10'
  : status === 'reserved' ? 'border-status-warning/60 bg-status-warning/10'
  : 'border-opsgrid-border bg-opsgrid-bg'

interface Props {
  doors: DockDoor[]
  trailers: YardTrailer[]
  onTrailerClick?: (trailer: YardTrailer) => void
}

export const YardMapPanel: FC<Props> = ({ doors, trailers, onTrailerClick }) => {
  const zones = groupTrailersByZone(trailers)
  const trailerByDoor = new Map(
    trailers.filter((t) => t.assignedDoorId).map((t) => [t.assignedDoorId as string, t])
  )

  return (
    <div className="space-y-6" data-testid="yard-map">
      {/* Dock wall */}
      <div>
        <h3 className="text-sm font-semibold text-opsgrid-text mb-2 flex items-center gap-1">
          <DoorOpen className="w-4 h-4" /> Dock Doors
        </h3>
        <div className="grid grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-2">
          {doors.map((door) => {
            const trailer = trailerByDoor.get(door.id)
            return (
              <div
                key={door.id}
                data-testid={`door-${door.id}`}
                className={`rounded-lg border-2 p-2 text-center ${doorColor(door.status)}`}
              >
                <p className="text-xs font-bold text-opsgrid-text">D{door.doorNumber}</p>
                <p className="text-[10px] capitalize text-opsgrid-text-secondary">{door.status}</p>
                {trailer && (
                  <button
                    onClick={() => onTrailerClick?.(trailer)}
                    className="mt-1 w-full text-[10px] truncate px-1 py-0.5 rounded bg-opsgrid-panel border border-opsgrid-border hover:border-opsgrid-primary"
                    title={trailer.trailerId}
                  >
                    {trailer.trailerId}
                  </button>
                )}
              </div>
            )
          })}
          {doors.length === 0 && (
            <p className="text-sm text-opsgrid-text-secondary col-span-full">No dock doors configured.</p>
          )}
        </div>
      </div>

      {/* Yard zones */}
      <div>
        <h3 className="text-sm font-semibold text-opsgrid-text mb-2 flex items-center gap-1">
          <Truck className="w-4 h-4" /> Yard Zones
        </h3>
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">
          {Object.entries(zones).map(([zone, zoneTrailers]) => (
            <div key={zone} className="rounded-lg border border-opsgrid-border p-3" data-testid={`zone-${zone}`}>
              <div className="flex justify-between text-xs text-opsgrid-text-secondary mb-2">
                <span className="font-semibold text-opsgrid-text">{zone}</span>
                <span>{zoneTrailers.length} trailer{zoneTrailers.length === 1 ? '' : 's'}</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {zoneTrailers.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => onTrailerClick?.(t)}
                    className={`text-[11px] px-2 py-1 rounded border hover:border-opsgrid-primary ${
                      t.detentionRisk === 'high'
                        ? 'border-status-alarm text-status-alarm'
                        : 'border-opsgrid-border text-opsgrid-text'
                    }`}
                  >
                    {t.trailerId}
                  </button>
                ))}
              </div>
            </div>
          ))}
          {Object.keys(zones).length === 0 && (
            <p className="text-sm text-opsgrid-text-secondary col-span-full">No trailers in the yard.</p>
          )}
        </div>
      </div>
    </div>
  )
}

export default YardMapPanel
