/**
 * An async handler whose rejection has no owner (FS-673).
 *
 * THE SHAPE. An `async` function passed to a JSX prop returns a promise, and the DOM event
 * system that eventually calls it throws that promise away. If it rejects, nothing catches
 * it — it becomes an unhandled rejection, which no user sees, no test asserts, and nothing
 * in the app reports.
 *
 * `KanbanBoard.handleDrop` was the instance, and its comment made the claim out loud: *"the
 * error still propagates to the caller"*. The caller is `KanbanColumn`'s `onDrop`, typed
 * `(columnId: string) => void` and invoked from a DOM drop handler. TypeScript permits
 * `() => Promise<void>` where `() => void` is expected — that assignability rule is exactly
 * where the rejection goes missing, and it is why the compiler had nothing to say.
 *
 * HOW IT SURFACED, which is the part worth keeping. Not from reading the file: from **one
 * error line in an otherwise green `vitest` run**. 1,056 tests passed and `Errors 1` sat
 * underneath, reported by the runner rather than by any assertion. A run that is green
 * except for a line nobody reads is how the next real one gets missed.
 *
 * THE SWEEP CAME BACK CLEAN — 36 handlers, all of them guarded once the one above was fixed
 * — and that is when this is cheapest to write and hardest to argue for. The line that
 * caused it is the positive control below.
 *
 * TWO DETECTOR CORRECTIONS, both of the recurring kind.
 *
 *   1. A handler is safe when it delegates to something that catches. `TaskDetailModal`'s
 *      seven handlers all call `runAction`, which has the try/catch; scanning only the
 *      immediate body reported all seven. Delegation is followed, one name at a time,
 *      transitively.
 *   2. Following delegation then still reported them, because the regex capturing an async
 *      arrow used `\([^)]*\)` for the parameter list — and `runAction(what: string, action:
 *      () => Promise<void>)` contains a nested `)`. `runAction` was never captured at all,
 *      so nothing could delegate to it. Parameter lists are scanned with balanced parens.
 *
 * Both were the detector calling correct code wrong, and both would have produced a list of
 * seven "defects" that a reader could have spent an afternoon on.
 */
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = path.resolve(__dirname, '..')

const walk = (dir: string): string[] =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) return walk(p)
    return /\.tsx$/.test(e.name) && !/\.test\./.test(e.name) ? [p] : []
  })

const FILES = walk(SRC)
const rel = (p: string) => path.relative(SRC, p).replace(/\\/g, '/')

/** Index past a balanced pair, starting one character inside it. */
function balanced(src: string, i: number, open: string, close: string): number {
  let depth = 1
  while (i < src.length && depth > 0) {
    if (src[i] === open) depth++
    else if (src[i] === close) depth--
    i++
  }
  return i
}

/**
 * `const NAME = [useCallback(] async (...) => { ... }` -> { NAME: body }.
 *
 * Parameter lists are matched with balanced parens rather than `[^)]*`, because a handler
 * that takes a callback — `(what: string, action: () => Promise<void>)` — contains a nested
 * `)` and would otherwise not be found at all.
 */
export function asyncBodies(src: string): Record<string, string> {
  const found: Record<string, string> = {}
  const decl = /const (\w+)\s*=\s*(?:useCallback\(\s*)?async\s*\(/g
  let m: RegExpExecArray | null
  while ((m = decl.exec(src))) {
    const afterParams = balanced(src, m.index + m[0].length, '(', ')')
    const arrow = src.indexOf('=>', afterParams)
    const brace = src.indexOf('{', arrow)
    if (arrow === -1 || brace === -1 || brace - arrow > 80) continue
    found[m[1]] = src.slice(brace, balanced(src, brace + 1, '{', '}'))
  }
  return found
}

/** Does this handler catch, itself or through something it calls? */
export function guarded(
  name: string,
  bodies: Record<string, string>,
  seen: string[] = [],
): boolean {
  if (seen.includes(name)) return false
  const body = bodies[name] ?? ''
  if (body.includes('catch')) return true
  return Object.keys(bodies).some(
    (other) =>
      other !== name &&
      new RegExp(`\\b${other}\\s*\\(`).test(body) &&
      guarded(other, bodies, [...seen, name]),
  )
}

/** (file, handler, guarded) for every awaiting async handler passed to a JSX prop. */
function handlers(): Array<{ file: string; name: string; safe: boolean }> {
  const rows: Array<{ file: string; name: string; safe: boolean }> = []
  for (const file of FILES) {
    const src = fs.readFileSync(file, 'utf8')
    const bodies = asyncBodies(src)
    for (const [name, body] of Object.entries(bodies)) {
      if (!body.includes('await')) continue
      if (!new RegExp(`\\bon[A-Z]\\w*=\\{${name}\\}`).test(src)) continue
      rows.push({ file: rel(file), name, safe: guarded(name, bodies) })
    }
  }
  return rows
}

describe('the detector', () => {
  it('finds handlers to check at all', () => {
    // Vacuity. A regex that stops matching reports a clean tree for the same reason a
    // broken grep does.
    expect(handlers().length).toBeGreaterThanOrEqual(20)
  })

  it('flags the line that caused this', () => {
    // POSITIVE CONTROL, and it is the real shape: try/finally with no catch, which is what
    // `handleDrop` had. The `finally` is correct and stays — it is the reset that stops the
    // board holding a task after a refused move — it just is not a catch.
    const before = `
      const handleDrop = async (columnId: string) => {
        try {
          await onDragEnd(draggedTaskId, columnId);
        } finally {
          setDraggedTaskId(null);
        }
      };
    `
    expect(guarded('handleDrop', asyncBodies(before))).toBe(false)
  })

  it('does not flag a handler that catches', () => {
    const after = `
      const handleDrop = async (columnId: string) => {
        try {
          await onDragEnd(draggedTaskId, columnId);
        } catch (error) {
          console.error('Failed to move task:', error);
        }
      };
    `
    expect(guarded('handleDrop', asyncBodies(after))).toBe(true)
  })

  it('does not flag a handler that delegates to one that catches', () => {
    // NEGATIVE CONTROL 2, and the reason the first two drafts were wrong. The nested `)`
    // in `runAction`'s parameter list is the whole point of the balanced-paren scan.
    const delegating = `
      const runAction = async (what: string, action: () => Promise<void>) => {
        try {
          await action();
        } catch (error) {
          console.error(\`Failed to \${what}:\`, error);
        }
      };
      const handleApprove = async () => {
        await runAction('approve this task', async () => {
          await approveTask(task.id, 'approve');
        });
      };
    `
    const bodies = asyncBodies(delegating)
    expect(Object.keys(bodies)).toContain('runAction')
    expect(guarded('handleApprove', bodies)).toBe(true)
  })

  it('does not loop forever on mutual delegation', () => {
    const circular = `
      const a = async () => { await b(); };
      const b = async () => { await a(); };
    `
    expect(guarded('a', asyncBodies(circular))).toBe(false)
  })

  it('reports the real tree as mostly guarded, not entirely unguarded', () => {
    // If this collapses the guard is calling correct code wrong, which is how a sweep
    // produces an afternoon of work and no defects.
    const rows = handlers()
    expect(rows.filter((r) => r.safe).length).toBeGreaterThanOrEqual(rows.length - 1)
  })
})

it('no async handler passed to a JSX prop can reject unowned', () => {
  const leaking = handlers()
    .filter((r) => !r.safe)
    .map((r) => `${r.file}:${r.name}`)
  expect(
    leaking,
    'An async function passed to a JSX prop returns a promise the DOM discards. If it ' +
      'rejects there is no caller to catch it — TypeScript allows () => Promise<void> ' +
      'where () => void is expected — so the failure becomes an unhandled rejection that ' +
      'no user sees and no assertion covers. Catch it in the handler, or delegate to ' +
      'something that does.',
  ).toEqual([])
})
