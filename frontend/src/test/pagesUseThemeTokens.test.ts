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

//: Hardcoded light-theme colour utilities. Deliberately not matching `text-white`, which is
//: legitimate on a coloured status chip in either theme.
const HARDCODED = /\b(?:text-gray-(?:[5-9]\d{2})|bg-gray-(?:\d{2,3})|bg-white|border-gray-\d{3})\b/g

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
    const hits = (readFileSync(file, 'utf8').match(HARDCODED) || []).length
    if (hits) out[file.slice(file.indexOf('src/'))] = hits
  }
  return out
}

describe('routed pages use the theme tokens', () => {
  // Measured 2026-08-03 by walking src/pages RECURSIVELY. A first pass at this number used
  // a non-recursive shell glob and reported one file; there are five. LOWER these as pages
  // are converted, never raise them, and a new page must not appear here at all.
  const KNOWN: Record<string, number> = {
    'src/pages/Kanban.tsx': 23,
    'src/pages/logistics/TransportationManagement.tsx': 8,
    'src/pages/logistics/YardManagement.tsx': 6,
    'src/pages/intake/IntakeInbox.tsx': 1,
    'src/pages/auth/Login.tsx': 1,
  }

  it('does not add a new page that hardcodes light-theme colours', () => {
    const found = offenders()
    const unexpected = Object.keys(found).filter((f) => !(f in KNOWN)).sort()
    expect(unexpected).toEqual([])
  })

  it('does not let a known page get worse', () => {
    const found = offenders()
    const worse = Object.entries(KNOWN)
      .filter(([file, cap]) => (found[file] ?? 0) > cap)
      .map(([file, cap]) => `${file}: ${found[file]} > ${cap}`)
    expect(worse).toEqual([])
  })

  it('the tokens it wants actually exist in the tailwind config', () => {
    // Otherwise this guard would push authors toward class names that silently do nothing —
    // which renders as unstyled text, i.e. the same defect by a different route.
    const config = readFileSync(join(__dirname, '..', '..', 'tailwind.config.js'), 'utf8')
    for (const token of ['bg', 'panel', 'border', 'text', 'text-secondary']) {
      expect(config).toContain(`'${token}':`)
    }
  })
})
