import { useTranslation } from 'react-i18next'
import { stageIndex } from '../guide'

/** Three plain stages instead of nine workflow states; the exact state stays in the case header. */
export function CaseProgress({ workflowState }: { workflowState: string }) {
  const { t } = useTranslation()
  const current = stageIndex(workflowState)
  const stages = [1, 2, 3].map((n) => ({ title: t(`progress.s${n}`), hint: t(`progress.s${n}Hint`) }))
  return (
    <ol className="case-progress" aria-label={t('progress.label')}>
      {stages.map((stage, index) => {
        const state = index < current ? 'done' : index === current ? 'current' : 'upcoming'
        return (
          <li key={stage.title} className={`progress-stage progress-${state}`} aria-current={state === 'current' ? 'step' : undefined}>
            <span className="progress-dot" aria-hidden="true">{state === 'done' ? '✓' : index + 1}</span>
            <span>
              <strong>{stage.title}</strong>
              <small>{stage.hint}</small>
              <em>{t(`progress.${state}`)}</em>
            </span>
          </li>
        )
      })}
    </ol>
  )
}
