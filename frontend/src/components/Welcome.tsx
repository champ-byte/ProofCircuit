import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { markOnboarded } from '../guide'
import { LANGUAGES } from '../i18n'
import { useSession } from '../session'
import type { DemoUser } from '../types/api'

const DEMO_MID = 'MID-DEMO-001'

type Role = 'owner' | 'staff' | 'reviewer'
const DESTINATION: Record<Role, string> = { owner: '/dashboard', staff: '/staff', reviewer: '/cases' }

/** First-visit chooser: language first (so the role cards are readable), then who you are. */
export function Welcome({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const { users, setIdentity } = useSession()
  const navigate = useNavigate()
  const [step, setStep] = useState<'lang' | 'role'>('lang')
  const current = i18n.resolvedLanguage ?? 'en'
  const demoUsers = users.filter((u) => u.mid === DEMO_MID)
  const byRole = (role: Role) => demoUsers.filter((u) => u.role === role)

  const choose = (user: DemoUser, role: Role) => {
    setIdentity(`${user.mid}/${user.handle}`)
    markOnboarded()
    onClose()
    navigate(DESTINATION[role])
  }
  const skip = () => {
    markOnboarded()
    onClose()
  }

  const roles: { role: Role; title: string; who: string; body: string }[] = [
    { role: 'owner', title: t('welcome.ownerTitle'), who: t('welcome.ownerWho'), body: t('welcome.ownerBody') },
    { role: 'staff', title: t('welcome.staffTitle'), who: t('welcome.staffWho'), body: t('welcome.staffBody') },
    { role: 'reviewer', title: t('welcome.reviewerTitle'), who: t('welcome.reviewerWho'), body: t('welcome.reviewerBody') },
  ]

  return (
    <div className="modal-backdrop welcome-backdrop">
      <div className="modal welcome" role="dialog" aria-modal="true" aria-labelledby="welcome-title" onKeyDown={(e) => e.key === 'Escape' && skip()}>
        <p className="eyebrow">{t('welcome.title')}</p>
        {step === 'lang' ? (
          <>
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
              <button type="button" className="link" onClick={skip}>{t('welcome.skip')}</button>
              <button type="button" className="button-primary" autoFocus onClick={() => setStep('role')}>{t('welcome.continue')} →</button>
            </div>
          </>
        ) : (
          <>
            <h2 id="welcome-title">{t('welcome.roleTitle')}</h2>
            <p className="sub">{t('welcome.roleBody')}</p>
            <div className="welcome-roles">
              {roles.map((r) => (
                <article key={r.role} className="welcome-role">
                  <h3>{r.title}</h3>
                  <p className="welcome-who">{r.who}</p>
                  <p>{r.body}</p>
                  <div className="welcome-role-actions">
                    {byRole(r.role).map((user) => (
                      <button key={user.handle} type="button" className="button-primary" onClick={() => choose(user, r.role)}>
                        {byRole(r.role).length > 1 ? user.display_name : t('welcome.start', { role: r.title })}
                      </button>
                    ))}
                  </div>
                </article>
              ))}
            </div>
            <p className="welcome-note">{t('welcome.paytmNote')}</p>
            <div className="modal-actions">
              <button type="button" onClick={() => setStep('lang')}>← {t('welcome.back')}</button>
              <button type="button" className="link" onClick={skip}>{t('welcome.skip')}</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
