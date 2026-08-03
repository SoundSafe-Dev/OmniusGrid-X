import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * A routed page must not hardcode light-theme colours (FS-409).
 *
 * The app shell renders dark by default and has a Light toggle, and its palette is a set of
 * CSS variables exposed as Tailwind tokens — `opsgrid-bg`, `opsgrid-panel`, `opsgrid-border`,
 * `opsgrid-text`, `opsgrid-text-secondary`, plus the `status-*` hues. A page written against
 * `text-gray-900` / `bg-white` looks correct in whichever theme the author had open and is
 * unreadable in the other.
 *
 * THIS IS NOT A STYLE PREFERENCE. `ShopFloor.tsx` shipped its heading as `text-gray-900` on
 * the dark shell: the h1 was invisible, every button label was washed out, and the input
 * placeholders could not be read. It passed `tsc`, passed 518 unit tests, and passed a DOM
 * sweep that counted text length and visible controls — the text WAS there, at almost the
 * same colour as what it sat on. Only looking at a screenshot found it.
 *
 * Scoped to `src/pages/` deliberately. Some components are legitimately light regardless of
 * theme — the correlation chat transcript is a white sheet on purpose, and the components
 * inside it are styled to match — so a blanket ban would be wrong.
 */

const PAGES = join(__dirname, '..', 'pages')

//: Only what actually breaks on the other theme, refined 2026-08-04 after the first version
//: flagged correct code.
//:
//:   light SURFACES  bg-white, bg-gray-50/100/200      — a pale card in a dark shell
//:   dark TEXT       text-gray-700/800/900             — invisible on a dark background
//:   light BORDERS   border-gray-100/200/300           — a pale rule in a dark shell
//:
//: NOT flagged, because they are correct in both themes and flagging them would send someone
//: to "fix" working code — which costs the same as missing a real defect and is harder to
//: notice: mid greys used as STATUS SWATCHES (`bg-gray-400`, `bg-gray-500` returned from a
//: getStatusColor), muted body text (`text-gray-500/600`), and anything carrying an opacity
//: modifier (`bg-gray-500/20`), which composites over whatever background it sits on.
const HARDCODED =
  /\b(?:text-gray-(?:700|800|900)|bg-gray-(?:50|100|200)|bg-white|border-gray-(?:100|200|300))\b(?!\/)/g

function tsxFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) tsxFiles(full, acc)
    else if (entry.name.endsWith('.tsx') && !entry.name.includes('.test.')) acc.push(full)
  }
  return acc
}

function offenders(): Record<string, number> {
  const out: Record<string, number> = {}
  for (const file of tsxFiles(PAGES)) {
    const source = readFileSync(file, 'utf8')
    let hits = 0
    // Per className string, so a light utility can be checked against the `dark:` variants
    // sitting beside it.
    for (const [, attr] of source.matchAll(/className=(?:\{`|["'`])([^"'`]*)/g)) {
      for (const [match] of attr.matchAll(HARDCODED)) {
        // PAIRED IS FINE. `bg-white dark:bg-gray-800` is complete theming — Tailwind is
        // configured `darkMode: 'class'` and uiStore toggles `dark` on <html>, so both
        // halves are live. Flagging it would send someone to "fix" a page that works, and a
        // guard that cries wolf gets ignored, which costs more than the defect it missed.
        const property = match.startsWith('bg-')
          ? 'bg-'
          : match.startsWith('text-')
            ? 'text-'
            : 'border-'
        if (attr.includes(`dark:${property}`)) continue
        hits += 1
      }
    }
    if (hits) out[file.slice(file.indexOf('src/'))] = hits
  }
  return out
}

describe('routed pages use the theme tokens', () => {
  //: Deliberate, not debt. Measured 2026-08-04 with the pair-aware detector below.
  //:
  //: Login's single `bg-white` is a fixed white tile behind the product logo, so the logo
  //: reads in either theme — the tile is the artwork's background, not the page's.
  //:
  //: THE FIRST VERSION OF THIS FILE LISTED FIVE PAGES AND 39 OCCURRENCES. Almost all of it
  //: was the detector's fault: mid greys returned from a `getStatusColor` as status dots,
  //: translucent chips like `bg-gray-500/20`, and — the biggest group — Kanban's complete
  //: `bg-white dark:bg-gray-800` pairs, which are correct theming by Tailwind's own
  //: mechanism (`darkMode: 'class'`, and uiStore toggles `dark` on <html>). Acting on that
  //: list would have meant rewriting about forty working usages.
  const ALLOWED: Record<string, number> = {
    'src/pages/auth/Login.tsx': 1,
  }

  it('no page hardcodes a light-theme colour without a dark pair', () => {
    const found = offenders()
    const unexpected = Object.keys(found).filter((f) => !(f in ALLOWED)).sort()
    expect(unexpected).toEqual([])
  })

  it('the allowances are exact, with no spare slots', () => {
    // A ceiling with room in it is a free pass for the next one. Same rule the phantom-field
    // ratchet enforces: one spare slot is one free defect.
    const found = offenders()
    expect(found).toEqual(ALLOWED)
  })

  it('the tokens it wants actually exist in the tailwind config', () => {
    // Otherwise this guard would push authors toward class names that silently do nothing —
    // which renders as unstyled text, i.e. the same defect by a different route.
    const config = readFileSync(join(__dirname, '..', '..', 'tailwind.config.js'), 'utf8')
    for (const token of ['bg', 'panel', 'border', 'text', 'text-secondary']) {
      expect(config).toContain(`'${token}':`)
    }
  })

  it('does not flag a light utility that carries a dark pair', () => {
    // Pins the correction itself: Kanban's approach must stay valid.
    const paired = 'className="bg-white dark:bg-gray-800 text-gray-900 dark:text-white"'
    expect([...paired.matchAll(HARDCODED)].length).toBeGreaterThan(0)
    const unpaired = [...paired.matchAll(HARDCODED)].filter(([m]) => {
      const prop = m.startsWith('bg-') ? 'bg-' : m.startsWith('text-') ? 'text-' : 'border-'
      return !paired.includes(`dark:${prop}`)
    })
    expect(unpaired).toEqual([])
  })

  it('does not flag a translucent chip or a status swatch', () => {
    for (const attr of ['className="bg-gray-500/20 text-gray-500"',
                        "className={'bg-gray-400'}"]) {
      expect([...attr.matchAll(HARDCODED)]).toEqual([])
    }
  })
})
