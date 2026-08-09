import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

/**
 * A component under `asChild` must forward its ref (FS-383).
 *
 * THE DEFECT. Radix's `asChild` renders through `Slot`, which CLONES the single child to
 * merge in its own ref and event handlers. A plain function component that destructures
 * only the props it knows about drops both silently. React warns about the ref; nothing
 * warns about the handlers, and the handlers are what make the thing work.
 *
 * Found on 2026-08-01 by a QA sweep. `StatCard` in TransportationManagement.tsx and
 * YardManagement.tsx was used inside nine and eight `<TooltipTrigger asChild>` wrappers
 * respectively. The symptom read as a cosmetic React warning in the console. It was not:
 * hovering "Total Shipments" against a running app produced **0** elements with
 * `role="tooltip"` and **0** Radix poppers. Every one of those tooltips was dead, and had
 * been for as long as the pattern existed.
 *
 * WHY A SWEEP AND NOT TWO TESTS. The two fixed instances are not interesting; the shape is.
 * `asChild` is used at many sites here, and each one is a place where someone can drop a
 * locally-defined component in and lose its behaviour with no failing test and no visible
 * error — only a warning in a console nobody is reading during a feature build.
 *
 * WHAT IT DELIBERATELY DOES NOT DO: it does not resolve imported components across files.
 * A component imported from `components/ui` is out of scope, because those are wrappers
 * around Radix primitives that already forward refs, and following imports would trade a
 * cheap reliable check for an expensive flaky one. The rule enforced is the one that was
 * actually broken: a component DEFINED IN THE SAME FILE and used under `asChild` must be a
 * `forwardRef`.
 */

const SRC = resolve(__dirname, '..')

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (entry !== 'node_modules') walk(full, out)
    } else if (/\.tsx$/.test(entry) && !/\.test\.tsx$/.test(entry)) {
      out.push(full)
    }
  }
  return out
}

/** Component names used as the direct child of an `asChild` trigger, in one file. */
function asChildComponents(source: string): string[] {
  const found: string[] = []
  // `asChild` may sit on a multi-line opening tag, so match to the closing `>` and then
  // take the next JSX element. Lowercase names are DOM elements and always accept a ref.
  const re = /asChild[^>]*>\s*<([A-Z][A-Za-z0-9_]*)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(source)) !== null) found.push(m[1])
  return [...new Set(found)]
}

/** True when `name` is defined in this file and is NOT a forwardRef. */
function definedLocallyWithoutForwardRef(source: string, name: string): boolean {
  const declaration = new RegExp(
    `(?:const|function|class)\\s+${name}\\b[^\\n]*`, 'g',
  )
  const matches = source.match(declaration)
  if (!matches) return false // imported, or not a top-level definition — out of scope
  // `const X = forwardRef<...>` / `const X = React.forwardRef(` both count as forwarding.
  return !matches.some((line) => /forwardRef/.test(line))
}

const FILES = walk(SRC)

describe('components used under asChild forward their ref', () => {
  it('finds the asChild pattern at all', () => {
    // A sweep that matches nothing passes for the wrong reason.
    const withAsChild = FILES.filter((f) => asChildComponents(readFileSync(f, 'utf8')).length > 0)
    expect(withAsChild.length).toBeGreaterThan(3)
  })

  it('has no locally-defined non-forwardRef component under asChild', () => {
    const offenders: string[] = []
    for (const file of FILES) {
      const source = readFileSync(file, 'utf8')
      for (const name of asChildComponents(source)) {
        if (definedLocallyWithoutForwardRef(source, name)) {
          offenders.push(`${file.replace(SRC, 'src')}: <${name}>`)
        }
      }
    }
    expect(
      offenders,
      'These components are cloned by Radix Slot, which merges in a ref AND event ' +
        'handlers. A plain function component drops both, leaving the trigger inert — ' +
        'not a warning, a dead control. Wrap the component in forwardRef and spread the ' +
        'remaining props onto its root element:\n  ' +
        offenders.join('\n  '),
    ).toEqual([])
  })

  it('recognises a forwardRef component as compliant', () => {
    // Guards the detector itself: if `definedLocallyWithoutForwardRef` stopped seeing
    // forwardRef, the test above would flag every fixed component and get disabled.
    const compliant = `
const StatCard = forwardRef<HTMLDivElement, Props>(({ label, ...rest }, ref) => <div ref={ref} {...rest} />)
<TooltipTrigger asChild><StatCard label="x" /></TooltipTrigger>
`
    expect(definedLocallyWithoutForwardRef(compliant, 'StatCard')).toBe(false)
  })

  it('would catch the defect it was written for', () => {
    // The original TransportationManagement.tsx shape, verbatim in miniature.
    const broken = `
const StatCard: FC<{ label: string }> = ({ label }) => <div>{label}</div>
<TooltipTrigger asChild><StatCard label="Total Shipments" /></TooltipTrigger>
`
    expect(asChildComponents(broken)).toContain('StatCard')
    expect(definedLocallyWithoutForwardRef(broken, 'StatCard')).toBe(true)
  })
})
