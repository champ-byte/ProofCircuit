import { useTranslation } from 'react-i18next'
import type { ReasoningMode } from '../types/api'

// Persistent honesty labels (PRD 13.2). Text carries meaning; color is decoration only.
export function StatusBadges({ mode }: { mode: ReasoningMode | null }) {
  const { t } = useTranslation()
  return (
    <ul className="badges" aria-label="Environment labels">
      <li className="badge badge-neutral">{t('badges.synthetic')}</li>
      <li className="badge badge-neutral">{t('badges.simulator')}</li>
      <li className={`badge ${mode?.mode === 'live' ? 'badge-accent' : 'badge-warn'}`}>
        {t('badges.reasoning', { label: mode ? mode.label : t('badges.checking') })}
      </li>
    </ul>
  )
}
