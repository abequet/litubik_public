// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
// i18n (M3): natural-key mode — the English UI string IS the key, so only
// fr.json is maintained; English needs no resource file (fallback = the key).
// Rule (CONTRIBUTING.md): every new UI string goes through t() with its French
// translation added to locales/fr.json in the same change.
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import fr from './locales/fr.json'

const STORAGE_KEY = 'litubik-lang'

i18n.use(initReactI18next).init({
  resources: { fr: { translation: fr } },
  lng: localStorage.getItem(STORAGE_KEY) || 'en',
  fallbackLng: 'en',
  // natural keys: dots/colons in the English text are literal, not separators
  keySeparator: false,
  nsSeparator: false,
  interpolation: { escapeValue: false }, // React already escapes
})

// WCAG 3.1.1: <html lang> follows the UI language (screen readers pick the
// voice from it); index.html boots with lang="en"
document.documentElement.lang = i18n.language
i18n.on('languageChanged', (lang) => {
  localStorage.setItem(STORAGE_KEY, lang)
  document.documentElement.lang = lang
})

export default i18n
