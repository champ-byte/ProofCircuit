import { useTranslation } from 'react-i18next'
import type { CaseSummary } from '../types/api'

const groups = [
  { key: 'needsAction', matches: (state: string) => !['CLOSED', 'WAITING_FOR_EVIDENCE', 'NEEDS_HUMAN_REVIEW'].includes(state), color: '#176b9b' },
  { key: 'waiting', matches: (state: string) => state === 'WAITING_FOR_EVIDENCE', color: '#d99b3b' },
  { key: 'review', matches: (state: string) => state === 'NEEDS_HUMAN_REVIEW', color: '#7e72ba' },
  { key: 'done', matches: (state: string) => state === 'CLOSED', color: '#2e9b84' },
]

export function WorkflowChart({ cases }: { cases: CaseSummary[] }) {
  const { t } = useTranslation()
  const values = groups.map((group) => ({ ...group, label: t(`chart.${group.key}`), cases: cases.filter((item) => group.matches(item.workflow_state)) }))
  const max = Math.max(1, ...values.map((group) => group.cases.length))
  const totalAmount = cases.reduce((sum, item) => sum + item.amount_paise, 0)
  return (
    <section className="workflow-chart" aria-labelledby="workflow-chart-title">
      <div className="workflow-chart-heading">
        <div><p className="eyebrow">{t('chart.eyebrow')}</p><h2 id="workflow-chart-title">{t('chart.title')}</h2><p>{t('chart.body')}</p></div>
        <div className="workflow-chart-total"><span>{t('chart.totalAmount')}</span><strong>{new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(totalAmount / 100)}</strong></div>
      </div>
      <div className="workflow-bars" role="img" aria-label={values.map((group) => t('chart.aria', { label: group.label, count: group.cases.length })).join(', ')}>
        {values.map((group) => <div className="workflow-bar-group" key={group.key}>
          <strong>{group.cases.length}</strong>
          <div className="workflow-bar-track"><span className="workflow-bar" style={{ height: `${Math.max(4, group.cases.length / max * 100)}%`, backgroundColor: group.color }} /></div>
          <span>{group.label}</span>
        </div>)}
      </div>
    </section>
  )
}
