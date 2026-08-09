/**
 * Every source directory is inside the coverage measurement (FS-541).
 *
 * THE DEFECT. `vitest.config.ts` included `src/components/ui/**` — one of the ten
 * directories under `src/components/`. The other nine (assets, charts, commands, common,
 * fleet, kanban, layout, nlp, yard) were **10,566 lines outside the measurement**, so the
 * four percentages described a subset chosen once and never revisited, and the ratchet
 * could not fall no matter how much untested component code was added.
 *
 * The config's own comment describes exactly this failure, for an even narrower include it
 * had already fixed: *"it measured the code we happened to have tested, so it could never
 * fall no matter how much untested code was added."* The scope was widened to five paths
 * and one of those five was itself a leaf — **the class was fixed at one depth and left
 * open at the next.**
 *
 * WHY A TEST AND NOT JUST THE FIX. The gap opened by ADDITION: somebody added
 * `src/components/fleet/` and did not think about a glob two levels up. That is not caught
 * reliably by review, and it recurs — the same shape as `overlays/dr` missing from the k8s
 * README (FS-520) and the six alert-test files listed by hand in CI (FS-537). In all three
 * the artefact was correct when written and wrong the moment the tree grew.
 *
 * WHAT THIS DOES NOT CHECK: that coverage is high, or that any particular file is tested.
 * Only that nothing is silently outside the number. A directory may be deliberately
 * excluded — `src/test/`, generated clients, mock fixtures — and each of those is named in
 * the config's `exclude`, which this reads.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOT = resolve(__dirname, '../..')
const SRC = join(ROOT, 'src')
const CONFIG = readFileSync(join(ROOT, 'vitest.config.ts'), 'utf8')

/** Directories under `src/` that hold product code, one level deep. */
function sourceDirectories(): string[] {
  const found: string[] = []
  const walk = (relative: string) => {
    const absolute = join(SRC, relative)
    for (const entry of readdirSync(absolute)) {
      const child = relative ? `${relative}/${entry}` : entry
      if (!statSync(join(SRC, child)).isDirectory()) continue
      found.push(child)
      // Two levels is enough: the defect was `components/ui` vs `components/*`, and
      // globbing at depth two covers everything below it.
      if (!relative) walk(child)
    }
  }
  walk('')
  return found
}

/**
 * The COVERAGE block's globs, read out of the config rather than restated here.
 *
 * Scoped to everything after `coverage: {`, because the config declares an `include:`
 * twice — once for which files are TEST files (`src/**\/*.{test,spec}.{ts,tsx}`) and once
 * for which files are MEASURED. The first version of this took the first match and
 * asserted against the test-file pattern, which fails against a correct config and would
 * have passed against a broken one the moment the two swapped order. Two keys with the
 * same name in one file is exactly where a naive parse goes wrong.
 */
const COVERAGE_BLOCK = CONFIG.slice(CONFIG.indexOf('coverage: {'))

function globsUnder(key: string): string[] {
  const block = COVERAGE_BLOCK.split(`${key}: [`)[1]?.split(']')[0] ?? ''
  return [...block.matchAll(/'([^']+)'/g)].map((match) => match[1])
}

const includedGlobs = () => globsUnder('include')
const excludedGlobs = () => globsUnder('exclude')

/**
 * Whether `glob` puts the whole of `directory` in or out of scope.
 *
 * ONLY `src/`-ROOTED GLOBS COUNT AS DIRECTORY SCOPES. The first version stripped `**` from
 * anywhere and treated an empty prefix as "matches everything", so the exclude entry
 * `'**\/*.test.{ts,tsx}'` — a FILE pattern, not a directory one — collapsed to `''` and
 * marked every directory as deliberately excluded. The whole-tree assertion then passed
 * against a config that measured one directory in ten.
 *
 * A mutation test caught it: narrowing the include back to `src/components/ui/**` failed
 * only the specific assertion below and not the general one, which is the signature of a
 * check that is agreeing with itself.
 */
function covers(glob: string, directory: string): boolean {
  if (!glob.startsWith('src/')) return false
  const prefix = glob.slice('src/'.length).replace(/\/?\*\*.*$/, '').replace(/\/\*.*$/, '')
  if (prefix === '' || prefix === '**') return true
  return directory === prefix || directory.startsWith(`${prefix}/`)
}

describe('the coverage measurement sees every source directory', () => {
  it('reads a non-empty include list from the config', () => {
    // Vacuity: a parse that returns nothing would make every assertion below pass by
    // finding no directories to complain about — while the config included nothing at all.
    expect(includedGlobs().length).toBeGreaterThanOrEqual(4)
    expect(includedGlobs()).toContain('src/api/**')
    // The test-file pattern must NOT be what we read: it is a different `include:` in the
    // same file, and matching it would make every assertion here describe the wrong list.
    expect(includedGlobs()).not.toContain('src/**/*.{test,spec}.{ts,tsx}')
  })

  it('finds the directories it is meant to be checking', () => {
    const directories = sourceDirectories()
    expect(directories).toContain('components')
    expect(directories).toContain('components/kanban')
    expect(directories.length).toBeGreaterThan(10)
  })

  it('leaves no source directory outside the measurement', () => {
    const included = includedGlobs()
    const excluded = excludedGlobs()

    const invisible = sourceDirectories().filter((directory) => {
      if (excluded.some((glob) => covers(glob, directory))) return false
      // A parent being included covers its children.
      return !included.some((glob) => covers(glob, directory))
    })

    expect(
      invisible,
      `these directories under src/ are in neither the coverage include nor the exclude, ` +
        `so their code is outside the four percentages entirely and the thresholds cannot ` +
        `fall however much untested code they gain. Add them to include, or to exclude ` +
        `with a reason. This is how src/components/{assets,charts,commands,common,fleet,` +
        `kanban,layout,nlp,yard} — 10,566 lines — sat outside the number.`,
    ).toEqual([])
  })

  it('includes all of src/components, not one directory inside it', () => {
    // Named specifically because this is the instance that happened, and because a future
    // narrowing would satisfy the general check above by adding nine sibling globs while
    // leaving the same trap for the tenth.
    expect(
      includedGlobs(),
      'the coverage include names a directory INSIDE src/components rather than the whole ' +
        'tree. Nine of ten were invisible last time this was written that way.',
    ).toContain('src/components/**')
  })
})
