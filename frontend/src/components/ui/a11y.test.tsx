import { render } from '@testing-library/react'
import { axe } from 'jest-axe'
import { describe, expect, it } from 'vitest'
import { Badge } from './Badge'
import { Button } from './Button'
import { Input } from './Input'
import { Modal } from './Modal'
import { Select } from './Select'
import { Table } from './Table'

// Accessibility baseline (task 6): the shared primitives must have no axe
// violations, so every screen built from them starts accessible.
//
// WIDENED FROM TWO TO SIX (FS-550/552). It covered `Button` and `Input` — and
// `Select` rendered an UNLABELLED COMBOBOX app-wide: the `<label>` had no
// `htmlFor`, the `<select>` no `id`, the error text no `role="alert"`, no
// `aria-describedby` and no `aria-invalid`. A screen reader announced "combo
// box" and nothing else, on every filter and form built from it.
//
// Its sibling one file away did all of this correctly with `useId()`, which is
// what makes it a defect rather than an omission — the pattern was established
// and not carried across.
//
// AND THE COVERAGE REPORT SAID `Select` WAS AT 100% OF LINES. It is imported by
// the barrel, so the module body executes; nothing rendered it. A file can be
// fully "covered" and never exercised, which is the same distinction FS-529 drew
// between a definition being tested and being reached.

describe('UI primitive accessibility', () => {
  it('Button has no violations', async () => {
    const { container } = render(<Button>Save</Button>)
    expect(await axe(container)).toHaveNoViolations()
  })

  it('Input with label + error is properly associated', async () => {
    const { container, getByLabelText } = render(
      <Input label="Email" error="required" defaultValue="" />
    )
    // label is wired to the control
    expect(getByLabelText('Email')).toBeInTheDocument()
    expect(await axe(container)).toHaveNoViolations()
  })

  it('Select with label + error is properly associated', async () => {
    const { container, getByLabelText } = render(
      <Select
        label="Workcell"
        error="required"
        options={[
          { value: 'a', label: 'Cell A' },
          { value: 'b', label: 'Cell B' },
        ]}
      />,
    )
    // The assertion that failed before FS-550: without `htmlFor`/`id` there is no
    // accessible name to query by, and this throws.
    expect(getByLabelText('Workcell')).toBeInTheDocument()
    expect(await axe(container)).toHaveNoViolations()
  })

  it('Select announces its error to a screen reader', async () => {
    const { getByRole, getByLabelText } = render(
      <Select label="Workcell" error="required" options={[{ value: 'a', label: 'A' }]} />,
    )
    // `role="alert"` is what makes a validation failure reach someone not looking at
    // the colour — the whole difference between an error being visible and being
    // perceivable.
    expect(getByRole('alert')).toHaveTextContent('required')
    expect(getByLabelText('Workcell')).toHaveAttribute('aria-invalid', 'true')
  })

  it('Table has no violations', async () => {
    // COMPOUND, not data-driven. The first version passed `columns`/`data`, which is a
    // different table component's API — `tsc` caught it, and a JS test would have rendered
    // an empty table and asserted it had no violations, which is true and worthless.
    const { container } = render(
      <Table>
        <Table.Head>
          <Table.Row>
            <Table.Header>Name</Table.Header>
          </Table.Row>
        </Table.Head>
        <Table.Body>
          <Table.Row>
            <Table.Cell>Press 1</Table.Cell>
          </Table.Row>
        </Table.Body>
      </Table>,
    )
    expect(await axe(container)).toHaveNoViolations()
  })

  it('Modal has no violations when open', async () => {
    const { container } = render(
      <Modal isOpen onClose={() => {}} title="Confirm">
        <p>Body</p>
      </Modal>,
    )
    expect(await axe(container)).toHaveNoViolations()
  })

  it('Badge has no violations', async () => {
    const { container } = render(<Badge>Running</Badge>)
    expect(await axe(container)).toHaveNoViolations()
  })
})
