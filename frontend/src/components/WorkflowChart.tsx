import type { CaseSummary } from '../types/api'

const groups = [
  { label: 'Needs action', matches: (state: string) => !['CLOSED', 'WAITING_FOR_EVIDENCE', 'NEEDS_HUMAN_REVIEW'].includes(state), color: '#176b9b' },
  { label: 'Waiting for proof', matches: (state: string) => state === 'WAITING_FOR_EVIDENCE', color: '#d99b3b' },
  { label: 'In review', matches: (state: string) => state === 'NEEDS_HUMAN_REVIEW', color: '#7e72ba' },
  { label: 'Done', matches: (state: string) => state === 'CLOSED', color: '#2e9b84' },
]

export function WorkflowChart({ cases }: { cases: CaseSummary[] }) {
  const values = groups.map((group) => ({ ...group, cases: cases.filter((item) => group.matches(item.workflow_state)) }))
  const max = Math.max(1, ...values.map((group) => group.cases.length))
  const totalAmount = cases.reduce((sum, item) => sum + item.amount_paise, 0)
  return (
    <section className="workflow-chart" aria-labelledby="workflow-chart-title">
      <div className="workflow-chart-heading">
        <div><p className="eyebrow">Where your cases stand</p><h2 id="workflow-chart-title">Disputes at a glance</h2><p>Each column is a count of real cases in this workspace. Open the table below to see each one.</p></div>
        <div className="workflow-chart-total"><span>Total amount at risk</span><strong>{new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(totalAmount / 100)}</strong></div>
      </div>
      <div className="workflow-bars" role="img" aria-label={values.map((group) => `${group.label}: ${group.cases.length} cases`).join(', ')}>
        {values.map((group) => <div className="workflow-bar-group" key={group.label}>
          <strong>{group.cases.length}</strong>
          <div className="workflow-bar-track"><span className="workflow-bar" style={{ height: `${Math.max(4, group.cases.length / max * 100)}%`, backgroundColor: group.color }} /></div>
          <span>{group.label}</span>
        </div>)}
      </div>
    </section>
  )
}
