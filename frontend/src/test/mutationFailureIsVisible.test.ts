/**
 * A mutation whose failure reaches no one is a button that lies.
 *
 * `useQuery` failures render as emptiness — that class has its own sweep next door.
 * `useMutation` failures render as **nothing at all**, which is worse in one specific way:
 * the user pressed the button on purpose, so they are already expecting a change, and the
 * absence of any response is indistinguishable from the moment before the list refreshes.
 *
 * WHAT IT FOUND.
 *
 *   `AdminPages` — create, update and delete user, plus the org-settings save. A failed
 *   delete left the row exactly where it was and said nothing. "Still there" is precisely
 *   what a successful delete looks like an instant before the refetch, so there was
 *   nothing to notice — and an admin who believes they revoked someone's access, and did
 *   not, has a security problem they cannot see.
 *
 *   `ERPIntegrations` — create, delete, test-connection and trigger-sync. Test-connection
 *   is the sharpest in the whole sweep: it writes its outcome into a per-integration map
 *   only on success, so a FAILED test left the PREVIOUS test's "healthy: connected" on
 *   screen. Not missing feedback — a stale claim presented as the current result, to
 *   somebody who pressed the button precisely to refresh that claim.
 *
 * Both files already contained the right idiom and skipped it locally: `AdminPages` uses
 * `alert` from `useDialog` for its missing-field checks, and `ERPIntegrations` has an
 * `onError` on `analyzeMut` and nowhere else. Method rule 18 — a guard wrong once is
 * likeliest wrong again, in the same file.
 *
 * THE PARSING IS THE POINT. The first version of this sweep looked for `onError` within a
 * fixed 600 characters of the declaration and produced two false positives out of four
 * files: `CommandPanel`, whose `mutationFn` body is long enough to push `onError` past the
 * window, and `AlarmRules`, which uses `mutateAsync` inside a try/catch. A window is a
 * guess about code shape. The options object has exact bounds, so they are counted.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')

const COMMENT = /\/\*[\s\S]*?\*\/|(?<![:'"`])\/\/[^\n]*/g
const MUTATION = /const\s+(\w+)\s*=\s*useMutation\s*[<(]/g

/** The `{ … }` passed to `useMutation`, by brace counting from the declaration.
 *  Returns '' if the braces never balance, which is treated as "cannot tell" and
 *  therefore surfaced — this sweep must not invent findings out of a parse failure. */
function optionsObject(source: string, from: number): string {
  const open = source.indexOf('{', from)
  if (open === -1) return ''
  let depth = 0
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') {
      depth--
      if (depth === 0) return source.slice(open, i + 1)
    }
  }
  return ''
}

export function mutationsWithNoErrorSurface(raw: string): string[] {
  const source = raw.replace(COMMENT, ' ')
  const silent: string[] = []
  for (const match of source.matchAll(MUTATION)) {
    const name = match[1]
    const options = optionsObject(source, match.index! + match[0].length - 1)
    // No parse, no claim.
    if (!options) continue
    // `onError` in its own options is the direct handling.
    if (/\bonError\s*:/.test(options)) continue
    // …or the component reads the flag itself and renders something.
    if (new RegExp(String.raw`\b${name}\.(?:isError|error)\b`).test(source)) continue
    // …or it is awaited via mutateAsync, where the try/catch at the call site is the
    // handler. AlarmRules does exactly this and was a false positive until it was.
    if (new RegExp(String.raw`\b${name}\.mutateAsync\b`).test(source)) continue
    silent.push(name)
  }
  return [...new Set(silent)]
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return sourceFiles(full)
    if (!entry.endsWith('.tsx') || entry.includes('.test.')) return []
    return [full]
  })
}

const FILES = sourceFiles(SRC)
const MUTATING = FILES.filter((f) => /useMutation\s*[<(]/.test(readFileSync(f, 'utf8')))
const OFFENDERS = MUTATING.map((file) => ({
  file: file.slice(SRC.length + 1),
  mutations: mutationsWithNoErrorSurface(readFileSync(file, 'utf8')),
})).filter((o) => o.mutations.length > 0)

describe('the mutation sweep is not vacuous', () => {
  it('finds the components that mutate', () => {
    // If `useMutation` stopped matching, every file would look safe and this suite would
    // pass while inspecting nothing — rule 21, and the reason the count is asserted.
    // 8 today. Asserted as a floor rather than an exact number so adding a mutating
    // page does not fail this, but deleting the pattern does.
    expect(MUTATING.length).toBeGreaterThanOrEqual(8)
  })

  it('flags a mutation that only handles success', () => {
    const bad = `
      const deleteMutation = useMutation({
        mutationFn: (id: string) => api.remove(id),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
      })
    `
    expect(mutationsWithNoErrorSurface(bad)).toEqual(['deleteMutation'])
  })

  it('accepts an onError however long the mutationFn is', () => {
    // The CommandPanel false positive: a fixed look-ahead window pushed `onError` out of
    // range because the request body in between ran to several hundred characters.
    const padding = "        // ".replace('//', '') + 'x'.repeat(1200)
    const good = `
      const submitCommand = useMutation({
        mutationFn: async (data) => {
          const body = '${padding}'
          return api.post('/commands/submit', body)
        },
        onSuccess: () => setFeedback('ok'),
        onError: (e) => setFeedback(e.message),
      })
    `
    expect(mutationsWithNoErrorSurface(good)).toEqual([])
  })

  it('accepts a mutation awaited through mutateAsync', () => {
    // The AlarmRules false positive: the handler is the try/catch at the call site.
    const good = `
      const deleteMutation = useMutation({ mutationFn: (id) => api.remove(id), onSuccess: refresh })
      const onDelete = async (rule) => {
        try { await deleteMutation.mutateAsync(rule.id) }
        catch (err) { await alert({ title: 'Could not delete the rule' }) }
      }
    `
    expect(mutationsWithNoErrorSurface(good)).toEqual([])
  })

  it('accepts a mutation whose isError the component renders', () => {
    const good = `
      const save = useMutation({ mutationFn: (p) => api.put('/settings', p), onSuccess: reset })
      return <div>{save.isError && <span>Could not save.</span>}</div>
    `
    expect(mutationsWithNoErrorSurface(good)).toEqual([])
  })

  it('flags only the silent one when a file has both kinds', () => {
    // Every real offender was in a file that already handled a NEIGHBOURING mutation
    // correctly. A file-level "does it mention onError" check would have cleared both.
    const mixed = `
      const analyzeMut = useMutation({ mutationFn: go, onSuccess: ok, onError: (e) => note(e) })
      const testMut = useMutation({ mutationFn: test, onSuccess: (r) => note(r) })
    `
    expect(mutationsWithNoErrorSurface(mixed)).toEqual(['testMut'])
  })

  it('says nothing when it cannot parse the options', () => {
    // A sweep that turns a parse failure into a finding is worse than one that misses:
    // it spends the reader's trust on noise.
    expect(mutationsWithNoErrorSurface('const m = useMutation(buildOptions())')).toEqual([])
  })
})

describe('no mutation fails in silence', () => {
  it('has no offenders', () => {
    expect(
      OFFENDERS.map(
        (o) =>
          `${o.file} — ${o.mutations.join(', ')} handle only success, so a failed ` +
          `request leaves the screen exactly as it was and the user cannot tell the ` +
          `action did not happen`,
      ),
    ).toEqual([])
  })
})
