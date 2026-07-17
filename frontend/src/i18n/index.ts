// i18n scaffolding (task 5). react-i18next initialized with an English resource
// bundle; feature strings migrate into namespaced JSON over time. Adding a locale
// is a new folder under locales/<lang>/ + a resources entry here.
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import enCommon from './locales/en/common.json'

export const defaultNS = 'common'

i18n.use(initReactI18next).init({
  resources: {
    en: { common: enCommon },
  },
  lng: 'en',
  fallbackLng: 'en',
  defaultNS,
  interpolation: { escapeValue: false }, // React already escapes
})

export default i18n
