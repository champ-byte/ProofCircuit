import { formatCountdown, formatIst, STATE_LABELS } from '../format'
import { secondsUntil, useNow } from '../hooks'
import type { CaseDetail } from '../types/api'

function inr(paise: number): string {
  return `₹${(paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function CaseHeader({ detail }: { detail: CaseDetail }) {
  const now = useNow(1000)
  const left = secondsUntil(detail.deadline_utc, now)
  return (
    <section className="case-header sticky" aria-label="Case summary">
      <div>
        <h1>
          {detail.external_dispute_id} <span className="sub">· {detail.merchant_name}</span>
        </h1>
        <div className="sub">
          Order <code>{detail.order_id}</code> · Transaction <code>{detail.transaction_id}</code> ·{' '}
          {detail.reason === 'requires_review' ? 'reason not confirmed (review)' : detail.reason.replaceAll('_', ' ')}
        </div>
      </div>
      <dl className="facts-row">
        <div>
          <dt>Amount at risk</dt>
          <dd className="num amount">{detail.amount_display}</dd>
        </div>
        <div>
          <dt>Response deadline</dt>
          <dd>
            {formatIst(detail.deadline_utc)}
            <div className={left <= 0 ? 'sub warn' : left < 6 * 3600 ? 'sub warn' : 'sub'} aria-live="off">
              {formatCountdown(left, true)}
            </div>
          </dd>
        </div>
        <div>
          <dt>Workflow</dt>
          <dd>{STATE_LABELS[detail.workflow_state] ?? detail.workflow_state}</dd>
        </div>
        <div>
          <dt>Provider status (simulator)</dt>
          <dd>
            <code>{detail.provider_status_raw ?? detail.provider_status}</code>
          </dd>
        </div>
        {detail.debit_amount_paise !== null && (
          <div>
            <dt>Reported debit</dt>
            <dd>
              {inr(detail.debit_amount_paise)} <span className="sub">(provider-reported)</span>
            </dd>
          </div>
        )}
        {detail.dispute_utr && (
          <div>
            <dt>Dispute UTR</dt>
            <dd>
              <code>{detail.dispute_utr}</code> <span className="sub">(provider-reported)</span>
            </dd>
          </div>
        )}
        {detail.flags.length > 0 && (
          <div>
            <dt>Flags</dt>
            <dd>{detail.flags.join(', ')}</dd>
          </div>
        )}
      </dl>
    </section>
  )
}
