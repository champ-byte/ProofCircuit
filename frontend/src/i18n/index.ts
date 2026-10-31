import i18n from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'
import bn from './locales/bn.json'
import en from './locales/en.json'
import gu from './locales/gu.json'
import hi from './locales/hi.json'
import kn from './locales/kn.json'
import ml from './locales/ml.json'
import mr from './locales/mr.json'
import pa from './locales/pa.json'
import ta from './locales/ta.json'
import te from './locales/te.json'

/** Interface languages. Staff messages from the backend stay in en/hi/mr (their configured locale). */
export const LANGUAGES = [
  { code: 'en', native: 'English', english: 'English' },
  { code: 'hi', native: 'हिन्दी', english: 'Hindi' },
  { code: 'mr', native: 'मराठी', english: 'Marathi' },
  { code: 'bn', native: 'বাংলা', english: 'Bengali' },
  { code: 'gu', native: 'ગુજરાતી', english: 'Gujarati' },
  { code: 'kn', native: 'ಕನ್ನಡ', english: 'Kannada' },
  { code: 'ml', native: 'മലയാളം', english: 'Malayalam' },
  { code: 'pa', native: 'ਪੰਜਾਬੀ', english: 'Punjabi (Gurmukhi)' },
  { code: 'ta', native: 'தமிழ்', english: 'Tamil' },
  { code: 'te', native: 'తెలుగు', english: 'Telugu' },
] as const

export type LanguageCode = (typeof LANGUAGES)[number]['code']

export const resources = { en, hi, mr, bn, gu, kn, ml, pa, ta, te }

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: Object.fromEntries(Object.entries(resources).map(([code, translation]) => [code, { translation }])),
    supportedLngs: LANGUAGES.map((l) => l.code),
    fallbackLng: 'en',
    load: 'languageOnly',
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false }, // React already escapes rendered text
    detection: { order: ['localStorage', 'navigator'], caches: ['localStorage'], lookupLocalStorage: 'proofsaathi.language' },
    returnNull: false,
  })

const syncLang = (lng: string) => {
  if (typeof document !== 'undefined') document.documentElement.lang = lng
}
syncLang(i18n.resolvedLanguage ?? 'en')
i18n.on('languageChanged', syncLang)

export default i18n
