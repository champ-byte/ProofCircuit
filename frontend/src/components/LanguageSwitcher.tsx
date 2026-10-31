import { useTranslation } from 'react-i18next'
import { LANGUAGES } from '../i18n'

/** Native-script names so a reader finds their language without reading English first. */
export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  const current = i18n.resolvedLanguage ?? 'en'
  return (
    <label className="language-switcher">
      <span className="visually-hidden">{t('app.language')}</span>
      <span aria-hidden="true" className="language-icon">अ/A</span>
      <select value={current} onChange={(event) => void i18n.changeLanguage(event.target.value)} title={current === 'en' ? undefined : t('app.translationNote')}>
        {LANGUAGES.map((lang) => (
          <option key={lang.code} value={lang.code} lang={lang.code}>
            {lang.native}{lang.code === 'en' ? '' : ` · ${lang.english}`}
          </option>
        ))}
      </select>
    </label>
  )
}
