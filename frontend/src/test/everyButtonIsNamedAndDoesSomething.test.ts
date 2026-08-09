/**
 * Every `<button>` has an accessible name and something to do (FS-551).
 *
 * THIRTEEN OF 96 HAD NO NAME. An icon-only `<button>` with no `aria-label` is announced by a
 * screen reader as "button" and nothing else. The list included **both sidebar logout
 * buttons**, two modal closes, two alarm-acknowledge controls, and the Kanban board/list view
 * toggle — so a screen-reader user could reach the control that ends their session and not be
 * told what it was.
 *
 * ONE HAD NO HANDLER. `KanbanColumn`'s chevron was a `<button>` with no `onClick`: focusable,
 * announced as a button, and silent when pressed. **That is worse than no affordance** — it
 * invites the action and then fails without saying so. It is presentational now, because
 * giving it behaviour is a feature decision and removing a false affordance is not.
 *
 * WHY THIS IS PARSED, NOT GREPPED, AND WHY THAT TOOK THREE GOES.
 *
 * The regex version reported **75 of 97** — most of the codebase, which is the signature of a
 * broken detector rather than a broken product (the same failure FS-529's first run made, at
 * 57%). Parsing the JSX properly took it to 18. Then two more corrections, in opposite
 * directions:
 *
 *  1. **Text nested deeper than one level was missed** — a button wrapping
 *     `<div><span>Save</span></div>` has a perfectly good name. Recursing found 7 more, down
 *     to 11.
 *  2. **Recursing with `forEachChild` descends into a child's ATTRIBUTES.** `<LogOut
 *     size={16} />` contains the expression `{16}`, which read as renderable content — so
 *     both sidebar logout buttons dropped OUT of the list. Walking `children` only put them
 *     back, at the true 13.
 *
 * The second is the instructive one: it made the detector *under*-report, and the two
 * buttons it hid were the most consequential in the set. A false negative in an
 * accessibility sweep is invisible by construction — nothing fails, and the control stays
 * unnamed.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const ROOT = resolve(__dirname, '../..')
const SRC = join(ROOT, 'src')

/** Attributes that give an element an accessible name. */
const NAMING_ATTRIBUTES = new Set(['aria-label', 'aria-labelledby', 'title'])

function sourceFiles(): string[] {
  const found: string[] = []
  const walk = (directory: string) => {
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry)
      if (statSync(path).isDirectory()) walk(path)
      else if (/\.tsx$/.test(entry) && !/\.(test|spec)\./.test(entry)) found.push(path)
    }
  }
  walk(SRC)
  return found
}

/**
 * Whether anything inside `node` renders text.
 *
 * WALKS `children` ONLY. Using `ts.forEachChild` also enters each child element's
 * attributes, so `<LogOut size={16} />` looks like content because of the `{16}` — which is
 * how both sidebar logout buttons disappeared from an earlier version of this sweep.
 */
function rendersText(node: ts.JsxElement | ts.JsxFragment): boolean {
  for (const child of node.children) {
    if (ts.isJsxText(child) && child.getText().trim().length > 0) return true
    if (ts.isJsxExpression(child) && child.expression) return true
    if ((ts.isJsxElement(child) || ts.isJsxFragment(child)) && rendersText(child)) return true
  }
  return false
}

interface ButtonSite {
  location: string
  named: boolean
  interactive: boolean
}

function buttons(): ButtonSite[] {
  const sites: ButtonSite[] = []
  for (const file of sourceFiles()) {
    const source = ts.createSourceFile(
      file,
      readFileSync(file, 'utf8'),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    )
    const visit = (node: ts.Node) => {
      if (ts.isJsxElement(node) && node.openingElement.tagName.getText() === 'button') {
        const attributes = node.openingElement.attributes.properties
        // A spread may carry anything, including `aria-label` and `onClick`, so it is not
        // evidence of a defect either way.
        const spread = attributes.some((a) => ts.isJsxSpreadAttribute(a))
        const named =
          spread ||
          attributes.some((a) => a.name && NAMING_ATTRIBUTES.has(a.name.getText())) ||
          rendersText(node)
        const interactive =
          spread || attributes.some((a) => a.name && a.name.getText() === 'onClick')
        sites.push({
          location: `${file.replace(`${ROOT}/`, '')}:${
            source.getLineAndCharacterOfPosition(node.getStart()).line + 1
          }`,
          named,
          interactive,
        })
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
  return sites
}

describe('every button is named and does something', () => {
  it('finds the buttons it is meant to be checking', () => {
    // Vacuity, and calibration. Zero means the parse broke; a number close to the total
    // being flagged below means the DETECTOR is broken, which is how the first version of
    // this reported 75 of 97.
    expect(buttons().length).toBeGreaterThan(50)
  })

  it('flags no more than a small fraction — a sweep that flags most of a tree is broken', () => {
    const all = buttons()
    const flagged = all.filter((b) => !b.named).length
    expect(
      flagged,
      `${flagged} of ${all.length} buttons read as unnamed. Above about a tenth, suspect the ` +
        `detector before the codebase: the regex version of this reported 75 of 97 by ` +
        `failing to see text nested inside child elements.`,
    ).toBeLessThan(all.length / 10)
  })

  it('leaves no button without an accessible name', () => {
    const unnamed = buttons().filter((b) => !b.named).map((b) => b.location)
    expect(
      unnamed,
      `these <button> elements have no aria-label, no title and no text — a screen reader ` +
        `announces "button" and nothing else. Both sidebar logout buttons were in this list, ` +
        `so a screen-reader user could reach the control that ends their session without ` +
        `being told what it was.`,
    ).toEqual([])
  })

  it('leaves no button without a handler', () => {
    const inert = buttons().filter((b) => !b.interactive).map((b) => b.location)
    expect(
      inert,
      `these <button> elements have no onClick. They are focusable and announced as buttons ` +
        `and do nothing when pressed, which is worse than no affordance: it invites the ` +
        `action and fails silently. Wire it, or make it presentational.`,
    ).toEqual([])
  })
})
