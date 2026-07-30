import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * An API client may choose what to SEND. It may not decide what the server MEANT.
 *
 * THE CLASS, found three times by hand before this file existed:
 *
 *   * `adaptAlert` did `geofenceName: … ?? a?.zoneId ?? ''`. The serializer sends `null` when
 *     the zone join does not resolve — deliberately, under a comment saying so — and the panel
 *     does `geofenceName ?? 'Zone name unavailable'`. `'' ?? x` is `''`, so the panel's
 *     fallback was unreachable and the row rendered blank.
 *   * `alertType: … ?? 'violation'` kept the original "every alert reads Violation" defect
 *     alive as a fallback, long after the field name was fixed on the server.
 *   * `center: { latitude: … ?? 0 }` placed every NULL-centred polygon zone at 0°N 0°E, where
 *     it passed the map's `typeof latitude === 'number'` filter and drew a circle.
 *
 * Every one of them was invisible to the whole frontend suite, because a coercion only shows
 * itself on incomplete data and fixtures are complete by default.
 *
 * WHAT IS AND IS NOT FLAGGED. The dangerous form is a LITERAL default on a value that came
 * from the server: `field: response.x ?? 0`. Not flagged:
 *
 *   * `a ?? b` where both sides are field reads — that is a RENAME (`geofenceId ?? zoneId`),
 *     which is one of the three legitimate fixes this codebase applies;
 *   * request-side defaults — `limit: params.limit ?? 1000` is the client deciding what to
 *     ask for, which is its business.
 *
 * The baseline below separates those from the real thing. It is a list of ALLOWED defaults,
 * each with a reason, and the assertion is that nothing new joins it.
 */

const API_DIR = join(__dirname, '..', 'api')

const COMMENT = /\/\*[\s\S]*?\*\/|(?<![:'"`])\/\/[^\n]*/g

/** `key: <anything> ?? <literal>` or `… || <literal>`, one per line. */
const LITERAL_DEFAULT =
  /^\s*(\w+):\s*[^,\n]*?(?:\?\?|\|\|)\s*('[^']*'|"[^"]*"|`[^`]*`|\d+(?:\.\d+)?|\[\]|\{\}|true|false|new Date\(\)[^,\n]*)\s*,\s*$/gm

/**
 * ALLOWED, with why. Two kinds only:
 *   REQUEST — the client choosing what to send, which is its decision to make.
 *   BENIGN  — an empty container or a flag the server always sends, where the default cannot
 *             be mistaken for a measurement.
 * Anything that would let a reader mistake a default for data does NOT belong here; it belongs
 * fixed.
 */
const ALLOWED: Record<string, string> = {
  'analysisSessions.ts:title':
    'REQUEST. The title of a session the client is creating, when the caller supplied none.',
  'client.ts:status':
    'REQUEST/ERROR. An axios failure with no HTTP response is reported as 500 — there is no '
    + 'status to preserve, and the caller needs a number.',
  'client.ts:message':
    'ERROR. The last resort in a chain that prefers the server detail, then the axios message.',
  'errors.ts:code':
    'ERROR ENVELOPE. Parsing a failure body that did not follow the error schema.',
  'errors.ts:message': 'ERROR ENVELOPE. Same chain as client.ts:message.',
  'geofencing.ts:acknowledged':
    'BENIGN. `acknowledged` is NOT NULL on geofence_alerts, and the safe direction for an '
    + 'alert whose flag is somehow absent is "needs attention".',
  'historian.ts:granularity': 'REQUEST. Query parameter default.',
  'historian.ts:offset': 'REQUEST. Query parameter default.',
  'historian.ts:limit': 'REQUEST. Query parameter default.',
  'maintenance.ts:vehicleNumber':
    'BENIGN. The serializer does not send it and the card needs a label; it falls back to the '
    + 'vehicle id, which is a real identifier for the same vehicle rather than a made-up value.',
  'maintenance.ts:byCategory':
    'BENIGN. An empty object renders no rows — it cannot be mistaken for a figure.',
  'maintenance.ts:monthlyBreakdown': 'BENIGN. An empty array renders no bars.',
  'maintenance.ts:totalSchedules':
    'BENIGN-ISH. The statistics endpoint always sends the three counters, and the panel has a '
    + 'separate error state, so this fires only on a 200 that omitted them. Worth revisiting '
    + 'if that ever becomes reachable: "0 overdue" is a claim.',
  'maintenance.ts:overdue': 'BENIGN-ISH. See maintenance.ts:totalSchedules.',
  'maintenance.ts:activeROs': 'BENIGN-ISH. See maintenance.ts:totalSchedules.',
  'notifications.ts:enabled': 'REQUEST. Creating a subscription defaults to enabled.',
  'notifications.ts:channel': 'MOCK-ONLY. Picks a channel for a fixture.',
  'notifications.ts:title': 'REQUEST. The title of a test notification the client is sending.',
  'twinOptimizer.ts:strategicEngineEmitted': 'REQUEST. Optimisation request flag.',
  'twinOptimizer.ts:recommendationType':
    'MOCK-ONLY. Inside `mockResponse`, which builds a fixture from the request.',
  'telemetry.ts:timestamp':
    'MOCK-ONLY. Inside the USE_MOCK branch of getLatest, shaping mock fixtures.',
  'telemetry.ts:value': 'MOCK-ONLY. Same branch as telemetry.ts:timestamp.',
  'transportation.ts:score': 'MOCK-ONLY. Inside the USE_MOCK branch of getCarrierCompliance.',
  'transportation.ts:driveHoursRemaining':
    'MOCK-ONLY, and getDriverHOS has no consumer. Note that `|| 0` here is the exact shape the '
    + 'backend warns about: `hos_drive_hours_remaining` is NULL for a driver who has not '
    + 'reported, and 0 means "out of hours". If this method is ever wired up, that has to go.',
  'transportation.ts:dutyHoursRemaining': 'MOCK-ONLY. See transportation.ts:driveHoursRemaining.',
  'transportation.ts:cycleHoursUsed': 'MOCK-ONLY. See transportation.ts:driveHoursRemaining.',
  'transportation.ts:currentStatus':
    'MOCK-ONLY. Reporting an unknown HOS status as off_duty is a claim; same caveat as the '
    + 'hours above.',
}

function apiFiles(): string[] {
  return readdirSync(API_DIR).filter(
    (name) => name.endsWith('.ts') && !name.includes('.test.') && name !== 'mockApi.ts',
  )
}

function found(): Map<string, string> {
  const hits = new Map<string, string>()
  for (const name of apiFiles()) {
    const source = readFileSync(join(API_DIR, name), 'utf8').replace(COMMENT, ' ')
    for (const match of source.matchAll(LITERAL_DEFAULT)) {
      hits.set(`${name}:${match[1]}`, match[0].trim())
    }
  }
  return hits
}

describe('the scan is not vacuous', () => {
  it('reads every api client', () => {
    expect(apiFiles().length).toBeGreaterThan(30)
  })

  it('finds the defaults that are known to be there', () => {
    // If the regex stops matching, the assertion below passes over an empty set — the failure
    // mode every guard in this repository has had at least once.
    expect(found().size).toBeGreaterThan(15)
  })

  it('would flag a response-side default', () => {
    // The positive control, run against the exact shape that reached the fleet map.
    const sample = "  return {\n    radius: z?.radiusMeters ?? 0,\n  }\n"
    const matches = [...sample.matchAll(LITERAL_DEFAULT)].map((m) => m[1])
    expect(matches).toEqual(['radius'])
  })

  it('does not flag a rename', () => {
    // The negative control. `a ?? b` between two field reads is one of the three legitimate
    // fixes this codebase applies, and a guard that forbade it would forbid the cure.
    const sample = "  return {\n    geofenceId: a?.geofenceId ?? a?.zoneId,\n  }\n"
    expect([...sample.matchAll(LITERAL_DEFAULT)]).toEqual([])
  })
})

describe('no api client invents a value the server did not send', () => {
  it('every literal default is recorded with a reason', () => {
    const undocumented = [...found().entries()]
      .filter(([key]) => !(key in ALLOWED))
      .map(([key, line]) => `${key}  —  ${line}`)

    expect(undocumented).toEqual([])
  })

  it('the baseline names nothing that is already gone', () => {
    // A baseline listing a default that no longer exists is stale, and a stale list is one
    // nobody trusts. Shrinking is the good direction, so this reports rather than blocks.
    const hits = found()
    const fixed = Object.keys(ALLOWED).filter((key) => !hits.has(key))
    if (fixed.length > 0) {
      console.warn(`these defaults are gone; remove them from ALLOWED: ${fixed.join(', ')}`)
    }
    expect(fixed.length).toBeLessThan(Object.keys(ALLOWED).length)
  })

  it('every reason says which kind it is', () => {
    // An entry reading "fine" is a gap with extra steps.
    const thin = Object.entries(ALLOWED).filter(
      ([, reason]) => !/^(REQUEST|BENIGN|BENIGN-ISH|ERROR|MOCK-ONLY)/.test(reason),
    )
    expect(thin.map(([key]) => key)).toEqual([])
  })
})
