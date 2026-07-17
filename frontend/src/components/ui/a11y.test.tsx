import { render } from '@testing-library/react'
import { axe } from 'jest-axe'
import { describe, expect, it } from 'vitest'
import { Button } from './Button'
import { Input } from './Input'

// Accessibility baseline (task 6): the shared primitives must have no axe
// violations, so every screen built from them starts accessible.

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
})
