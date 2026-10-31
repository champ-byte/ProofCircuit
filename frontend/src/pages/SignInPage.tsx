import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { firstName, homeFor, type Role, SIGN_IN_ROLES, signInUsers } from '../roles'
import { useSession } from '../session'
import type { DemoUser } from '../types/api'

/** Demo sign-in: one card per role, one button per person. No passwords; the server issues the session. */
export function SignInPage() {
  const { t } = useTranslation()
  const { users, identity, setIdentity } = useSession()
  const navigate = useNavigate()
  const people = signInUsers(users)

  const choose = (user: DemoUser) => {
    setIdentity(`${user.mid}/${user.handle}`)
    navigate(homeFor(user.role), { replace: true })
  }

  return (
    <section className="signin" aria-labelledby="signin-title">
      <h1 id="signin-title">{t('welcome.roleTitle')}</h1>
      <p className="sub">{t('signin.body')}</p>
      <div className="welcome-roles">
        {SIGN_IN_ROLES.map((role: Role) => {
          const members = people.filter((u) => u.role === role)
          return (
            <article key={role} className="welcome-role">
              <h2>{t(`welcome.${role}Title`)}</h2>
              <p className="welcome-who">{t(`welcome.${role}Who`)}</p>
              <p>{t(`welcome.${role}Body`)}</p>
              <div className="welcome-role-actions">
                {members.map((user) => {
                  const current = identity === `${user.mid}/${user.handle}`
                  return (
                    <button key={user.handle} type="button" className="button-primary" aria-pressed={current} onClick={() => choose(user)}>
                      {t('signin.as', { name: firstName(user.display_name) })}
                    </button>
                  )
                })}
              </div>
            </article>
          )
        })}
      </div>
      {users.length > 0 && people.length === 0 && <p role="alert" className="error">{t('signin.none')}</p>}
      <p className="welcome-note">{t('welcome.paytmNote')}</p>
    </section>
  )
}
