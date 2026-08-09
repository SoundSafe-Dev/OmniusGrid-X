import { describe, expect, it } from 'vitest'
import { STATUS_COLORS } from './constants'

/**
 * A badge must not paint its text the same colour as its background.
 *
 * `info` was `bg-opsgrid-primary text-white`. `--color-primary` is `#fafafa` in the
 * DEFAULT dark theme and `#171717` in light, so every `info` badge in the app
 * rendered as a blank white pill in the theme most people use: the ERP type column,
 * the admin role chips, the NLP domain and priority tags, the fleet vehicle count,
 * the Compliance Assistant's "Form" marker. Ten call sites, all illegible, and none
 * of them wrong at the call site — the variant itself was.
 *
 * It survived because it is legible in light theme and because no test renders a
 * badge and inspects contrast. This one does not either; it asserts the rule that
 * makes the collision impossible.
 *
 * THE RULE: a background that follows the theme (`bg-opsgrid-*`, a CSS variable
 * that flips between near-black and near-white) must pair with foreground text that
 * follows the theme too — `text-opsgrid-bg`, which is by definition the opposite
 * end. A fixed `text-white` against a variable background is a coin flip on which
 * theme the reader has.
 *
 * Fixed backgrounds (`bg-status-*`, `bg-packml-*`) are exempt: they do not move
 * with the theme, so a fixed foreground beside them is a real decision.
 */

const THEME_BACKGROUND = /\bbg-opsgrid-[\w-]+/
const THEME_FOREGROUND = 'text-opsgrid-bg'

describe('STATUS_COLORS', () => {
  it('never pairs a theme-following background with a fixed text colour', () => {
    const offenders = Object.entries(STATUS_COLORS)
      .filter(([, classes]) => THEME_BACKGROUND.test(classes))
      .filter(([, classes]) => !classes.includes(THEME_FOREGROUND))
      .map(([key, classes]) => `${key}: "${classes}"`)

    expect(offenders, offenders.join('\n')).toEqual([])
  })

  it('info is legible in both themes', () => {
    expect(STATUS_COLORS.info).toContain('text-opsgrid-bg')
    expect(STATUS_COLORS.info).not.toContain('text-white')
  })

  it('every entry sets both a background and a foreground', () => {
    for (const [key, classes] of Object.entries(STATUS_COLORS)) {
      expect(classes, `${key} has no background`).toMatch(/\bbg-/)
      expect(classes, `${key} has no text colour`).toMatch(/\btext-/)
    }
  })
})
