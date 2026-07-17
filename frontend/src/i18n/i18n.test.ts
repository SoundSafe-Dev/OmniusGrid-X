import { describe, expect, it } from 'vitest'
import i18n from './index'

describe('i18n', () => {
  it('initializes English and resolves keys', () => {
    expect(i18n.language).toBe('en')
    expect(i18n.t('common.loading')).toBe('Loading…')
    expect(i18n.t('nav.dashboard')).toBe('Dashboard')
  })
})
