/**
 * Every `<label>` is associated with a control (FS-553).
 *
 * FORTY-FIVE OF SIXTY WERE NOT. A `<label>` with no `htmlFor`, sitting beside its input
 * rather than wrapping it, is a caption — not a label. A screen reader announces the control
 * as "edit text" with no name, clicking the text does not focus the field, and the form is
 * navigable only by sighted mouse users. `GeofencingPanel` had eight, `CreateTaskModal` seven,
 * `KanbanFilters` six.
 *
 * This is the same defect FS-550 fixed inside `ui/Select`, one layer out: there the shared
 * primitive was unlabelled, here the pages that hand-roll their own form markup instead of
 * using it are.
 *
 * THREE FORMS COUNT AS ASSOCIATION, and a detector that knows one over-reports by a factor
 * of four:
 *
 *   1. `htmlFor` pointing at the control's `id` — the explicit form.
 *   2. The label WRAPPING its control — implicit association, perfectly valid, ten sites.
 *   3. The control being a component that labels itself, like `ui/Input`, which takes a
 *      `label` prop and wires it with `useId()`.
 *   4. The label wrapping `{children}` — a generic `Field` wrapper. `ShopFloor` defines
 *      `<label><span>{label}</span>{children}</label>` and passes each input in. At the call
 *      site the label really does wrap its control; a static walk sees only an expression
 *      and cannot know what it will hold. Found by this guard on its first run, which is the
 *      FOURTH idiom in a file whose whole subject is a detector that knew one.
 *
 * The first measurement said "55 of 60 unassociated" by knowing only the first form. Ten of
 * those wrap their control and are correct. That is the fourth detector this week to
 * over-report by not knowing a second idiom, and the number it produced — 92% of a tree —
 * was large enough to be dismissed rather than acted on.
 *
 * IDS ARE COMPONENT-SCOPED, and the first codemod run got that wrong. It generated
 * `id="title"` and `id="description"` from the label text alone, which collide the moment
 * two forms are mounted together — and **a duplicate id does not error**: the label silently
 * points at the first match in the document, so the association reads as fixed and is not.
 * Every generated id now carries its component's name.
 *
 * THE ELEVEN LEFT are labels whose sibling is a `ui/Input` — those need the `label` prop
 * rather than an adjacent `<label>`, which is a component change rather than an attribute —
 * plus three whose control is nested inside a wrapper div. Both are listed below with what
 * they need, so the remainder is a finite set rather than a silent tail.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const ROOT = resolve(__dirname, '../..')
const SRC = join(ROOT, 'src')

const NATIVE_CONTROLS = new Set(['input', 'select', 'textarea'])
const SELF_LABELLING = /^(Input|Select|Textarea)$/

/**
 * Labels not yet associated, with what each needs. An entry is a form field a screen
 * reader announces without a name.
 */
const UNASSOCIATED: Record<string, string> = {
  'components/commands/CommandPanel.tsx':
    'sibling is a ui/Input, which labels itself from a `label` prop — pass it instead of ' +
    'rendering an adjacent <label>',
  'components/nlp/ContextManagementModal.tsx':
    'four siblings are ui/Input (use the `label` prop) and one control is nested inside a ' +
    'wrapper div rather than being the next sibling',
  'pages/admin/AuditLogs.tsx':
    'the control is nested inside a wrapper div, so the codemod could not see it as the ' +
    'next sibling',
  'pages/intake/IntakeInbox.tsx':
    'two siblings are ui/Input (use the `label` prop) and one control is nested in a div',
}

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

/** Whether the label wraps a control — implicit association, form (2). */
function wrapsAControl(node: ts.JsxElement): boolean {
  let found = false
  const visit = (child: ts.Node) => {
    if (found) return
    const tag = ts.isJsxElement(child)
      ? child.openingElement.tagName.getText()
      : ts.isJsxSelfClosingElement(child)
        ? child.tagName.getText()
        : null
    if (tag && (NATIVE_CONTROLS.has(tag) || SELF_LABELLING.test(tag))) {
      found = true
      return
    }
    // Form (4). `{children}` inside a label means the label wraps whatever the caller
    // passes — association happens at the call site and cannot be seen from here.
    // Narrow on purpose: only the literal identifier `children`, not any expression, or
    // this would excuse every label containing interpolated text.
    if (ts.isJsxExpression(child) && child.expression?.getText() === 'children') {
      found = true
      return
    }
    for (const grandchild of (child as ts.JsxElement).children ?? []) visit(grandchild)
  }
  for (const child of node.children) visit(child)
  return found
}

interface LabelSite {
  file: string
  line: number
  associated: boolean
}

function labels(): LabelSite[] {
  const sites: LabelSite[] = []
  for (const file of sourceFiles()) {
    const source = ts.createSourceFile(
      file,
      readFileSync(file, 'utf8'),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    )
    const visit = (node: ts.Node) => {
      if (ts.isJsxElement(node) && node.openingElement.tagName.getText() === 'label') {
        const hasFor = node.openingElement.attributes.properties.some(
          (a) => a.name && a.name.getText() === 'htmlFor',
        )
        sites.push({
          file: file.replace(`${SRC}/`, ''),
          line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1,
          associated: hasFor || wrapsAControl(node),
        })
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
  return sites
}

/** Every literal `id="..."` in the tree, by value. */
function staticIds(): Map<string, Set<string>> {
  const byValue = new Map<string, Set<string>>()
  for (const file of sourceFiles()) {
    for (const match of readFileSync(file, 'utf8').matchAll(/\bid="([a-z0-9-]+)"/g)) {
      const files = byValue.get(match[1]) ?? new Set<string>()
      files.add(file)
      byValue.set(match[1], files)
    }
  }
  return byValue
}

describe('every label is associated with a control', () => {
  it('finds the labels it is meant to be checking', () => {
    expect(labels().length).toBeGreaterThan(40)
  })

  it('counts a wrapping label as associated', () => {
    // Form (2). Without this the sweep reports 55 of 60 — 92% of a tree, which is a number
    // large enough to be dismissed rather than acted on.
    const source = ts.createSourceFile(
      'x.tsx',
      '<label>Name <input /></label>',
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    )
    let checked = false
    const visit = (node: ts.Node) => {
      if (ts.isJsxElement(node) && node.openingElement.tagName.getText() === 'label') {
        expect(wrapsAControl(node)).toBe(true)
        checked = true
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
    expect(checked).toBe(true)
  })

  it('leaves no unassociated label outside the recorded remainder', () => {
    const unexpected = labels()
      .filter((l) => !l.associated)
      .filter((l) => !(l.file in UNASSOCIATED))
      .map((l) => `${l.file}:${l.line}`)

    expect(
      unexpected,
      `these <label> elements have no htmlFor and do not wrap their control, so they are ` +
        `captions rather than labels: the control is announced with no name and clicking ` +
        `the text does not focus it. Add htmlFor + a matching id, wrap the control, or use ` +
        `ui/Input's \`label\` prop.`,
    ).toEqual([])
  })

  it('no two files use the same literal id', () => {
    // The mistake the first codemod run made. `id="title"` from the label text alone
    // collides across forms, and a duplicate id does not error — the label points at the
    // first match, so the association reads as fixed and is not.
    const collisions = [...staticIds().entries()]
      .filter(([, files]) => files.size > 1)
      .map(([id, files]) => `${id} in ${files.size} files`)
    expect(collisions).toEqual([])
  })

  it('every recorded remainder still has an unassociated label', () => {
    // A stale entry reports fixed markup as outstanding, and the next reader stops trusting
    // the list — the failure FS-504 cost on a different allowlist.
    const withUnassociated = new Set(
      labels().filter((l) => !l.associated).map((l) => l.file),
    )
    const stale = Object.keys(UNASSOCIATED).filter((file) => !withUnassociated.has(file))
    expect(stale).toEqual([])
  })
})
