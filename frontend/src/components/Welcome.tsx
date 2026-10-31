import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { markOnboarded } from '../guide'
import { LANGUAGES } from '../i18n'

/** First-visit language chooser; Continue goes on to the sign-in page (where you pick who you are). */
export function Welcome({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const current = i18n.resolvedLanguage ?? 'en'

  const close = () => {
    markOnboarded()
    onClose()
  }
  const next = () => {
    close()
    navigate('/signin')
  }

  return (
    <div className="modal-backdrop welcome-backdrop">
      <div className="modal welcome" role="dialog" aria-modal="true" aria-labelledby="welcome-title" onKeyDown={(e) => e.key === 'Escape' && close()}>
        <p className="eyebrow">{t('welcome.title')}</p>
        <h2 id="welcome-title">{t('welcome.langTitle')}</h2>
        <p className="sub">{t('welcome.langBody')}</p>
        <div className="welcome-langs" role="group" aria-label={t('app.language')}>
          {LANGUAGES.map((lang) => (
            <button
              key={lang.code}
              type="button"
              lang={lang.code}
              aria-pressed={current === lang.code}
              className={current === lang.code ? 'welcome-lang active' : 'welcome-lang'}
              onClick={() => void i18n.changeLanguage(lang.code)}
            >
              <strong>{lang.native}</strong>
              <span>{lang.english}</span>
            </button>
          ))}
        </div>
        <div className="modal-actions">
          <button type="button" className="link" onClick={close}>{t('welcome.skip')}</button>
          <button type="button" className="button-primary" autoFocus onClick={next}>{t('welcome.continue')} →</button>
        </div>
      </div>
    </div>
  )
}
