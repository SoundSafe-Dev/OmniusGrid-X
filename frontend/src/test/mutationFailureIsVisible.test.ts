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

/**
 * The same class in the other idiom (FS-478).
 *
 * Everything above is scoped to `useMutation`, which is how most of this codebase mutates
 * — and is therefore blind to the pages that do it by hand: an `async` handler that awaits
 * an api call and catches with `console.error`. Structurally invisible to the sweep, and
 * exactly the same defect: the user pressed a button, nothing changed, and nothing said so.
 *
 * It found five, in two files. `IntakeInbox` upload and analyse — analyse is the sharper of
 * the two, because the spinner stops and the row stays as it was, which is what "there was
 * nothing to analyse" looks like. And three in `ContextManagementModal`, where the modal
 * closes on success, so a failure leaves it open — indistinguishable from still saving.
 *
 * WHY THE HEURISTIC IS NARROW. It requires an awaited `…Api.<verb>` call within the
 * preceding window AND a catch whose body only logs. A broader version flagged every
 * defensive `catch { console.warn }` around optional enrichment, which is not this defect
 * and would have made the list unreadable.
 */
export function silentHandRolledMutations(raw: string): string[] {
  const source = raw.replace(COMMENT, ' ')
  const found: string[] = []
  const CATCH = /catch\s*\((\w+)?\)?\s*\{([^}]*)\}/g
  const MUTATING_CALL =
    /\bawait\s+\w+Api\.(?:create|update|delete|upload|analyze|dispatch|send|post|approve|reject|trigger|start|complete|activate|assign|move|issue|clock|add|remove|attach|detach|link|cancel|pause|resume)\w*\s*\(/i
  let match: RegExpExecArray | null
  while ((match = CATCH.exec(source))) {
    const body = match[2]
    if (!/console\.(?:error|warn|log)/.test(body)) continue
    // Anything that puts the failure on screen clears it.
    if (/set\w*(?:Error|Message|Toast|Alert|Status)/i.test(body)) continue
    if (/alert\(|toast|notify|showError/i.test(body)) continue
    const before = source.slice(Math.max(0, match.index - 900), match.index)
    if (!MUTATING_CALL.test(before)) continue
    const handler = (before.match(/const (\w+) = async/g) || []).slice(-1)[0]
    found.push(handler ? handler.replace(/const (\w+) = async/, '$1') : 'anonymous handler')
  }
  return [...new Set(found)]
}

const HAND_ROLLED = FILES.map((file) => ({
  file: file.slice(SRC.length + 1),
  handlers: silentHandRolledMutations(readFileSync(file, 'utf8')),
})).filter((o) => o.handlers.length > 0)

describe('the hand-rolled sweep is not vacuous', () => {
  it('recognises the shape it is looking for', () => {
    const silent = `
      const handleSave = async () => {
        try { await thingApi.update(x) } catch (e) { console.error('nope', e) }
      }`
    expect(silentHandRolledMutations(silent)).toEqual(['handleSave'])
  })

  it('clears a handler that surfaces the failure', () => {
    const surfaced = `
      const handleSave = async () => {
        try { await thingApi.update(x) } catch (e) { console.error(e); setActionError('no') }
      }`
    expect(silentHandRolledMutations(surfaced)).toEqual([])
  })

  it('ignores a defensive catch around something that does not mutate', () => {
    // The reason the heuristic is narrow. Optional enrichment that logs and carries on is
    // not this defect, and flagging it would bury the ones that are.
    const enrichment = `
      const load = async () => {
        try { await thingApi.list() } catch (e) { console.warn('optional', e) }
      }`
    expect(silentHandRolledMutations(enrichment)).toEqual([])
  })
})

describe('no hand-rolled mutation fails in silence', () => {
  it('has no offenders', () => {
    expect(
      HAND_ROLLED.map(
        (o) =>
          `${o.file} — ${o.handlers.join(', ')} await a mutation and report failure only ` +
          `to the console, so the user who pressed the button sees the screen exactly as ` +
          `it was`,
      ),
    ).toEqual([])
  })
})

/**
 * The third place the same class hides: a mutation defined in a HOOK (FS-480).
 *
 * Everything above scans `.tsx`, because that is where components live. Mutation hooks live
 * in `src/hooks/*.ts` and were outside the sweep entirely — sixteen of them, including the
 * six OTA operations in `useFleet.ts`. Two of those are the safety actions: `useYankAgentRelease`
 * pulls a release that is going badly, and `useCancelAgentRollout` stops a rollout mid-flight.
 * A failed yank left the release listed exactly as it was, which is what a successful one
 * looks like for the moment before the list refetches.
 *
 * THE OBLIGATION IS THE CALLER'S, NOT THE HOOK'S. A hook returning `useMutation` is a
 * library: it has no screen to render on, and forcing an `onError` into it would put a
 * message in the wrong place. So this asks of each USED hook whether its call site surfaces
 * the failure, by any of the three idioms this codebase actually uses:
 *
 *   `save.isError` / `save.error`   read the flag and render something
 *   `save.mutateAsync`              awaited, so the try/catch at the call site is the handler
 *   `save.mutate(x, { onError })`   per-call options — which `ErrorTriageDetail` uses, and
 *                                   which an earlier version of this check did not know
 *                                   about, reporting it as silent when it was not
 *
 * AND ONLY WHERE THE HOOK IS USED. Eight of the sixteen have no caller at all — exported
 * from `src/hooks/index.ts` and never imported by a component. There is no user to fail in
 * front of, so flagging them here would be noise; they are dead exports, which is a
 * different and much smaller problem.
 */
const HOOK_DIR = join(SRC, 'hooks')

export function mutationHooks(source: string): string[] {
  const clean = source.replace(COMMENT, ' ')
  const names: string[] = []
  let current = ''
  for (const line of clean.split('\n')) {
    const declared = line.match(/^export function (\w+)/)
    if (declared) current = declared[1]
    if (/return useMutation/.test(line) && current) names.push(current)
  }
  return [...new Set(names)]
}

export function callSiteSurfacesFailure(source: string, hook: string): boolean | null {
  const clean = source.replace(COMMENT, ' ')
  const used = clean.match(new RegExp(String.raw`const\s+(\w+)\s*=\s*${hook}\s*\(`))
  if (!used) return null // not called here
  const variable = used[1]
  if (new RegExp(String.raw`\b${variable}\.(?:isError|error|mutateAsync)\b`).test(clean)) {
    return true
  }
  // Per-call options: `variable.mutate(arg, { onError: … })`
  const perCall = new RegExp(String.raw`\b${variable}\.mutate\s*\([\s\S]{0,600}?onError`)
  return perCall.test(clean)
}

const HOOK_FILES = readdirSync(HOOK_DIR).filter((f) => f.endsWith('.ts') && !f.includes('.test.'))
const PAGES = FILES.map((f) => readFileSync(f, 'utf8'))

const UNSURFACED = HOOK_FILES.flatMap((file) =>
  mutationHooks(readFileSync(join(HOOK_DIR, file), 'utf8')).flatMap((hook) => {
    const verdicts = PAGES.map((page) => callSiteSurfacesFailure(page, hook))
    const callers = verdicts.filter((v) => v !== null)
    if (callers.length === 0) return [] // dead export, not this defect
    return callers.every((v) => v === false) ? [`${file} — ${hook}`] : []
  }),
)

describe('the hook sweep knows what counts as handling', () => {
  it('finds the mutation hooks', () => {
    const found = HOOK_FILES.flatMap((f) =>
      mutationHooks(readFileSync(join(HOOK_DIR, f), 'utf8')),
    )
    expect(found.length).toBeGreaterThan(10)
    expect(found).toContain('useCancelAgentRollout')
  })

  it('accepts a caller that reads the flag', () => {
    expect(callSiteSurfacesFailure('const save = useThing()\nif (save.isError) x', 'useThing')).toBe(true)
  })

  it('accepts per-call onError, which an earlier version did not', () => {
    const perCall = `const save = useThing()
      save.mutate({ id }, { onSuccess: ok, onError: () => note() })`
    expect(callSiteSurfacesFailure(perCall, 'useThing')).toBe(true)
  })

  it('rejects a caller that only shows a spinner', () => {
    const spinner = `const save = useThing()
      <Button loading={save.isPending} onClick={() => save.mutate({ id })} />`
    expect(callSiteSurfacesFailure(spinner, 'useThing')).toBe(false)
  })

  it('says nothing about a file that does not call it', () => {
    expect(callSiteSurfacesFailure('const other = useSomethingElse()', 'useThing')).toBeNull()
  })
})

describe('no mutation hook fails in silence at every call site', () => {
  it('has no offenders', () => {
    expect(
      UNSURFACED.map(
        (entry) =>
          `${entry} is called and no caller reads isError, awaits mutateAsync, or passes ` +
          `onError — so a failed request leaves the screen as it was`,
      ),
    ).toEqual([])
  })
})


/**
 * The fourth shape, and the only one here that is not a mutation at all (FS-481).
 *
 * Everything above asks whether a failed WRITE reaches the user. This asks about a failed
 * READ — specifically the handler that changes what is being looked at, then fetches what
 * belongs to it:
 *
 *   const handleSelect = async (thing) => {
 *     setCurrent(thing)                                 // the label moves immediately
 *     try   { setRows(await api.getRows(thing.id)) }    // the content arrives later
 *     catch { console.error(e) }                        // …or never
 *   }
 *
 * On failure the label has moved and the content has not, so the PREVIOUS thing's data sits
 * under the NEW thing's name. That is a worse failure than showing nothing, and it is the
 * reason this is a separate check rather than a wider version of the ones above: a silent
 * write leaves the screen truthful-but-stale, while this one makes it actively wrong, and
 * an operator has no reason to doubt it.
 *
 * `CorrelationAIPane.handleSessionSelect` was the one occurrence — a failed transcript fetch
 * left another investigation's conversation under the newly selected session's title.
 *
 * NARROW ON PURPOSE. It requires the setter to be called with the handler's OWN parameter
 * (so it is the selection changing, not incidental state), the awaited read to come after
 * it, and a catch that neither sets state, alerts, nor rethrows. Loosening any of the three
 * floods the list with ordinary loaders, which are not this defect.
 */
export function staleAfterFailedSwitch(source: string): string[] {
  const clean = source.replace(COMMENT, ' ')
  const found: string[] = []
  const HANDLER = /const (\w+) = async \(\s*(\w+)[^)]*\)\s*(?::[^=]*)?=>\s*\{/g
  let match: RegExpExecArray | null
  while ((match = HANDLER.exec(clean))) {
    const [, name, param] = match
    const body = clean.slice(match.index, match.index + 2500).split(/\n  const \w+ = /)[0]
    const setIndex = body.search(new RegExp(`set[A-Z]\\w*\\(\\s*${param}\\b`))
    if (setIndex < 0) continue
    const readIndex = body.search(/await\s+\w+Api\.\w+\s*\(/)
    if (readIndex < 0 || readIndex < setIndex) continue
    const caught = body.match(/catch\s*\((\w+)?\)?\s*\{([^}]*)\}/)
    if (!caught) continue
    if (/set\w+|alert\(|toast|throw/.test(caught[2])) continue
    found.push(name)
  }
  return [...new Set(found)]
}

const STALE = FILES.map((file) => ({
  file: file.slice(SRC.length + 1),
  handlers: staleAfterFailedSwitch(readFileSync(file, 'utf8')),
})).filter((o) => o.handlers.length > 0)

describe('the stale-switch sweep is not vacuous', () => {
  it('recognises the shape it is looking for', () => {
    const stale = `
      const handleSelect = async (thing) => {
        setCurrent(thing)
        try { setRows(await thingApi.getRows(thing.id)) } catch (e) { console.error(e) }
      }`
    expect(staleAfterFailedSwitch(stale)).toEqual(['handleSelect'])
  })

  it('clears a handler that empties the stale view and says why', () => {
    const fixed = `
      const handleSelect = async (thing) => {
        setCurrent(thing)
        try { setRows(await thingApi.getRows(thing.id)) }
        catch (e) { console.error(e); setRows([]); setLoadError('could not load') }
      }`
    expect(staleAfterFailedSwitch(fixed)).toEqual([])
  })

  it('ignores a loader that does not change what is being looked at first', () => {
    // An ordinary fetch-on-mount has nothing stale to leave behind, because no label moved.
    const loader = `
      const load = async (id) => {
        try { setRows(await thingApi.getRows(id)) } catch (e) { console.error(e) }
      }`
    expect(staleAfterFailedSwitch(loader)).toEqual([])
  })
})

describe('no failed load leaves the previous subject under the new one\'s name', () => {
  it('has no offenders', () => {
    expect(
      STALE.map(
        (o) =>
          `${o.file} — ${o.handlers.join(', ')} switch the selection before fetching what ` +
          `belongs to it, so a failed fetch leaves the previous subject's data on screen ` +
          `under the new subject's name`,
      ),
    ).toEqual([])
  })
})

/**
 * The fifth shape: a mutation that is not an api call (FS-483).
 *
 * `silentHandRolledMutations` keys on `await …Api.<verb>(`. `Kanban.handleDragEnd` awaits
 * `moveTask(…)` — a function destructured from the kanban store — and the `api.post` it
 * wraps lives in `kanbanStore.tsx`, two files away from the `catch`. No window over this
 * file could have seen a mutation happening.
 *
 * `moveTask` posts BEFORE it updates local state, so on failure the card re-renders in the
 * column it came from. That is also exactly what a mis-drop looks like: the operator reads
 * it as their own miss, drags again, and the board and the server go on disagreeing.
 *
 * TWO EXEMPTIONS, BOTH ON PRINCIPLE RATHER THAN BY NAME:
 *
 *   A catch that RETURNS is propagating the failure by value, not swallowing it.
 *   `CorrelationAIPane.handleSessionMissingForUpload` returns `null`, and `DataSourcesPanel`
 *   branches on that and rethrows into a surfaced `uploadError`. Same lesson as the hook
 *   check above — the obligation can live at the call site.
 *
 *   A catch that only WARNS is the defensive-enrichment shape this file's first heuristic
 *   was deliberately narrowed to exclude. `generateSessionTitle` failing costs a session its
 *   auto-title and nothing else.
 *
 * Without those two the check reports two offenders that are not offenders, and a sweep that
 * spends the reader's trust on noise stops being run.
 */
const MUTATING_VERB =
  'create|update|delete|upload|analyze|dispatch|send|post|approve|reject|trigger|start|' +
  'complete|activate|assign|move|issue|clock|add|remove|attach|detach|link|cancel|pause|' +
  'resume|save|submit|archive|restore'

export function silentIndirectMutations(raw: string): string[] {
  const source = raw.replace(COMMENT, ' ')
  const found: string[] = []
  const BARE = new RegExp(String.raw`\bawait\s+(?:${MUTATING_VERB})[A-Z]\w*\s*\(`, 'i')
  const CATCH = /catch\s*\((\w+)?\)?\s*\{([^}]*)\}/g
  let match: RegExpExecArray | null
  while ((match = CATCH.exec(source))) {
    const body = match[2]
    if (!/console\.(?:error|log)/.test(body)) continue
    if (/set\w*(?:Error|Message|Toast|Alert|Status)/i.test(body)) continue
    if (/alert\(|toast|notify|showError/i.test(body)) continue
    // Propagated by value — the caller decides, and this file cannot see that decision.
    if (/\breturn\b|\bthrow\b/.test(body)) continue
    const before = source.slice(Math.max(0, match.index - 900), match.index)
    if (!BARE.test(before)) continue
    const handler = (before.match(/const (\w+) = (?:async|useCallback\(async)/g) || []).slice(-1)[0]
    found.push(handler ? handler.replace(/const (\w+) = .*/, '$1') : 'anonymous handler')
  }
  return [...new Set(found)]
}

const INDIRECT = FILES.map((file) => ({
  file: file.slice(SRC.length + 1),
  handlers: silentIndirectMutations(readFileSync(file, 'utf8')),
})).filter((o) => o.handlers.length > 0)

describe('the indirect-mutation sweep is not vacuous', () => {
  it('recognises the shape it is looking for', () => {
    // Kanban.handleDragEnd verbatim, before FS-483.
    const silent = `
      const handleDragEnd = async (id, col) => {
        try { await moveTask(id, col) } catch (e) { console.error('Failed to move task:', e) }
      }`
    expect(silentIndirectMutations(silent)).toEqual(['handleDragEnd'])
  })

  it('clears a handler that surfaces the failure', () => {
    const surfaced = `
      const handleDragEnd = async (id, col) => {
        try { await moveTask(id, col) } catch (e) { console.error(e); setMoveError('no') }
      }`
    expect(silentIndirectMutations(surfaced)).toEqual([])
  })

  it('exempts a catch that hands the failure back to its caller', () => {
    const propagated = `
      const recover = async () => {
        try { return (await createReplacementSession()).id }
        catch (e) { console.error(e); return null }
      }`
    expect(silentIndirectMutations(propagated)).toEqual([])
  })

  it('exempts a warn around optional enrichment', () => {
    const enrichment = `
      const label = async () => {
        try { await createSessionTitle(id) } catch (e) { console.warn('optional', e) }
      }`
    expect(silentIndirectMutations(enrichment)).toEqual([])
  })

  it('ignores a call whose name does not claim to change anything', () => {
    const reader = `
      const load = async () => {
        try { await fetchBoard() } catch (e) { console.error(e) }
      }`
    expect(silentIndirectMutations(reader)).toEqual([])
  })
})

describe('no indirect mutation fails in silence', () => {
  it('has no offenders', () => {
    expect(
      INDIRECT.map(
        (o) =>
          `${o.file} — ${o.handlers.join(', ')} await something named as a mutation and ` +
          `report failure only to the console, so the user who acted sees the screen ` +
          `exactly as it was`,
      ),
    ).toEqual([])
  })
})
