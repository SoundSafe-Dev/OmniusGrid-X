/**
 * A polled query whose consumer never reads its error (FS-655).
 *
 * THE SHAPE. react-query keeps the last successful `data` across a failed refetch. That is
 * the right default — a blank screen every time a poll blips would be worse — but it means a
 * component that destructures only `data` cannot tell a live reading from one taken an
 * unknown time ago. On a POLLED query that is not a transient state: the poll retries
 * forever, so the wrong reading stays on screen for as long as the endpoint is down, and
 * nothing about the page changes.
 *
 * The cold-start form is worse and is what this sweep was written after. With no data yet,
 * `data?.count || 0` is **zero**, and zero renders as a fact:
 *
 *   * `Header.tsx` hid the alarm badge behind `count > 0`, so an alarm feed that had never
 *     answered rendered as a plant with **no active alarms** — in the corner of every page.
 *   * `Alarms.tsx` showed "Active 0", and the card beside it computes `total - count`, so it
 *     reported **every alarm on the page as acknowledged**.
 *
 * Both were one missing `isError`. This is `failureIsNotEmptiness` carried across from a
 * rendered phrase to a rendered NUMBER, and from a one-shot fetch to a poll — neither of
 * which that sweep can see.
 *
 * WHY AN ALLOWLIST WITH REASONS rather than a count. A count can be satisfied by deleting a
 * poll, and a poll deleted is a screen that stops updating — the exact trade this exists to
 * refuse.
 */
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = path.resolve(__dirname, '..')

const walk = (dir: string): string[] =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) return walk(p)
    return /\.tsx?$/.test(e.name) && !/\.test\./.test(e.name) ? [p] : []
  })

const FILES = walk(SRC)
const rel = (p: string) => path.relative(SRC, p).replace(/\\/g, '/')

/** Hooks that wrap a `useQuery` carrying a `refetchInterval`. */
function polledHooks(): Set<string> {
  const found = new Set<string>()
  for (const file of FILES) {
    const src = fs.readFileSync(file, 'utf8')
    const decls = [...src.matchAll(/export (?:const|function) (use\w+)/g)]
    decls.forEach((m, i) => {
      const start = m.index! + m[0].length
      const end = i + 1 < decls.length ? decls[i + 1].index! : src.length
      if (src.slice(start, end).includes('refetchInterval')) found.add(m[1])
    })
  }
  return found
}

/**
 * Call sites that destructure a polled hook.
 *
 * Only the destructuring form is matched, and that is a real limit rather than an oversight:
 * `const q = useThing()` hands the consumer the whole query object, so it *can* read
 * `q.isError` and the question this sweep asks does not have a static answer. The
 * destructuring form is the one where the consumer has already chosen what it will look at.
 */
function callSites() {
  const hooks = polledHooks()
  const sites: { file: string; line: number; hook: string; reads: boolean }[] = []
  for (const file of FILES) {
    if (!file.endsWith('.tsx')) continue
    const src = fs.readFileSync(file, 'utf8')
    for (const hook of hooks) {
      const re = new RegExp(String.raw`(?:const|let)\s*\{([^}]*)\}\s*=\s*${hook}\(`, 'g')
      for (const m of src.matchAll(re)) {
        sites.push({
          file: rel(file),
          line: src.slice(0, m.index!).split('\n').length,
          hook,
          reads: /\b(isError|error|isLoadingError|status)\b/.test(m[1]),
        })
      }
    }
  }
  return sites
}

/**
 * Call sites that read only `data` from a polled query, with the reason each is acceptable.
 * **Only ever shrinks.** Empty as of 2026-08-11.
 */
const ALLOWED: Record<string, string> = {}

describe('the measurement is real', () => {
  it('finds the polled hooks', () => {
    // Vacuity: a regex that matched nothing would report every consumer clean.
    expect(polledHooks().size).toBeGreaterThan(5)
  })

  it('finds consumers of them', () => {
    expect(callSites().length).toBeGreaterThan(0)
  })

  it('can tell a consumer that reads the error from one that does not', () => {
    // Positive control. Without this the sweep passes by classifying everything as safe —
    // the failure mode that let three earlier sweeps in this repo report clean trees.
    const sites = callSites()
    expect(sites.some((s) => s.reads)).toBe(true)
  })
})

describe('every polled query says when it is failing', () => {
  it('has no consumer reading only data', () => {
    const blind = callSites()
      .filter((s) => !s.reads)
      .filter((s) => !(`${s.file}:${s.hook}` in ALLOWED))
      .map((s) => `${s.file}:${s.line} ${s.hook}`)

    expect(blind, blind.join('\n  ')).toEqual([])
  })

  it('has no stale allowlist entries', () => {
    const live = new Set(callSites().map((s) => `${s.file}:${s.hook}`))
    const gone = Object.keys(ALLOWED).filter((k) => !live.has(k))
    expect(gone, `no longer present: ${gone.join(', ')}`).toEqual([])
  })
})
