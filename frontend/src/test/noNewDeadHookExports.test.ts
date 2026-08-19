/**
 * Eight exported hooks nothing imports. This stops it growing (FS-575).
 *
 * The frontend twin of `test_no_new_unreachable_modules.py`. An exported hook with no consumer
 * reads as available capability: it is typed, it compiles, it appears in autocomplete, and the
 * next person to need that data writes a second one rather than discovering this.
 *
 * WHAT IS HERE, AND WHY IT IS RECORDED RATHER THAN SILENTLY DELETED.
 *
 * **All six `useFeatureFlags` exports are unused, and the backend serves the API.**
 * `app/api/feature_flags.py` mounts a full CRUD router and `featureFlagsApi` wraps it. So the
 * feature-flag system exists end to end and **nothing in the product consults a flag** — which
 * is a different and more interesting fact than "dead code". Deleting the hooks would leave the
 * backend serving an API with no client at all; wiring them is a product decision about whether
 * this codebase gates behaviour on flags.
 *
 * `useWorkcells` and `useOrganizations` are two of nine in `useAssets.ts`. Both wrap endpoints
 * that exist and are read elsewhere through direct api calls, so they are duplication rather
 * than absence — the shape rule 55 warns about, and the reason they are recorded rather than
 * removed: the next person adding a workcell list should use one of the two, and this says
 * which is which.
 *
 * THE DETECTOR IS NAME-BASED and deliberately loose. A hook referenced anywhere else in `src/`
 * counts as used, including from a test — because a hook with only a test is a different
 * finding (tested and unreached, FS-529's distinction) and conflating the two would make this
 * list say something it has not checked.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const SRC = resolve(__dirname, '..')
const HOOKS = join(SRC, 'hooks')

/** Exported hooks with no consumer, and what each one is. */
const DEAD_EXPORTS: Record<string, string> = {
  useFeatureFlags:
    'The whole feature-flag client is unused while the BACKEND serves the API — ' +
    'app/api/feature_flags.py mounts full CRUD. Nothing in the product gates behaviour on a ' +
    'flag. Wiring or removing is a product decision, not a cleanup.',
  useFeatureFlag: 'Same module, same decision.',
  useFeatureFlagList: 'Same module, same decision.',
  useCreateFeatureFlag: 'Same module, same decision.',
  useUpdateFeatureFlag: 'Same module, same decision.',
  useDeleteFeatureFlag: 'Same module, same decision.',
  useWorkcells:
    'Duplication, not absence: workcells are read elsewhere through a direct api call. ' +
    'Two ways to fetch one list is rule 55 — the copies diverge silently — so this records ' +
    'which is which for whoever adds the third.',
  useOrganizations: 'Same shape as useWorkcells.',
}

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry)
    if (statSync(path).isDirectory()) return sourceFiles(path)
    return /\.tsx?$/.test(entry) ? [path] : []
  })
}

/** `name -> defining file` for every export in `src/hooks/`. */
function hookExports(): Map<string, string> {
  const exported = new Map<string, string>()
  for (const file of sourceFiles(HOOKS)) {
    if (/\.test\./.test(file)) continue
    const source = ts.createSourceFile(
      file,
      readFileSync(file, 'utf8'),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    )
    const visit = (node: ts.Node) => {
      const isExported = ts
        .getCombinedModifierFlags(node as ts.Declaration)
        & ts.ModifierFlags.Export
      if (isExported) {
        if (ts.isFunctionDeclaration(node) && node.name) {
          exported.set(node.name.getText(), file)
        } else if (ts.isVariableStatement(node)) {
          for (const declaration of node.declarationList.declarations) {
            exported.set(declaration.name.getText(), file)
          }
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
  return exported
}

function unused(): string[] {
  const exported = hookExports()
  // THIS FILE IS NOT A CONSUMER. It names every entry in `DEAD_EXPORTS` and in its own
  // prose, and it lives under `src/`, so the first version counted its own inventory as
  // usage and reported every recorded entry as wired. An inventory that satisfies itself
  // is the emptiest possible guard — and it is the same shape as the vi.mock sweep reading
  // its own docstring (FS-544) and the doc-citation guard flagging its own confession
  // (FS-557). Three times now, in three different languages.
  const consumers = sourceFiles(SRC).filter(
    (file) => !file.endsWith('noNewDeadHookExports.test.ts'),
  )
  const dead: string[] = []
  for (const [name, definedIn] of exported) {
    const referenced = consumers.some(
      (file) =>
        file !== definedIn && new RegExp(`\\b${name}\\b`).test(readFileSync(file, 'utf8')),
    )
    if (!referenced) dead.push(name)
  }
  return dead.sort()
}

describe('no new dead hook exports', () => {
  it('finds the exports it is meant to be checking', () => {
    // Vacuity. An AST walk that returns nothing passes this file over an empty set while
    // every dead hook in the tree stays dead.
    expect(hookExports().size).toBeGreaterThan(20)
    expect([...hookExports().keys()]).toContain('useFeatureFlags')
  })

  it('does not flag a hook that is used', () => {
    // Calibration: a detector reporting most of the directory is broken, not a discovery.
    expect(unused().length).toBeLessThan(hookExports().size / 2)
  })

  it('leaves no unrecorded dead export', () => {
    const unrecorded = unused().filter((name) => !(name in DEAD_EXPORTS))
    expect(
      unrecorded,
      `these hooks are exported and nothing imports them. An unused export reads as ` +
        `available capability — typed, compiling, in autocomplete — so the next person who ` +
        `needs that data writes a second one rather than finding this. Wire it, delete it, ` +
        `or record it with what it actually is.`,
    ).toEqual([])
  })

  it('every recorded export is still dead', () => {
    // A stale entry reports wired code as dead, and the next reader stops trusting the
    // list — the failure FS-504 cost on a different allowlist, and FS-558 cost on the
    // backend's module baseline where two entries described live modules.
    const stillDead = new Set(unused())
    const wired = Object.keys(DEAD_EXPORTS).filter(
      (name) => hookExports().has(name) && !stillDead.has(name),
    )
    expect(
      wired,
      `these are recorded as dead and now have a consumer; remove their entries`,
    ).toEqual([])
  })

  it('every recorded export still exists', () => {
    const gone = Object.keys(DEAD_EXPORTS).filter((name) => !hookExports().has(name))
    expect(gone, `these were deleted; remove their entries too`).toEqual([])
  })
})
