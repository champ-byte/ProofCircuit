import { useTranslation } from 'react-i18next'
import { formatCountdown, formatIst, reasonLabel, stateLabel } from '../format'
import { secondsUntil, useNow } from '../hooks'
import type { CaseDetail } from '../types/api'
import { useView } from '../view'

function inr(paise: number): string {
  return `₹${(paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function CaseHeader({ detail }: { detail: CaseDetail }) {
  const { t } = useTranslation()
  const now = useNow(1000)
  const { detailed } = useView()
  const left = secondsUntil(detail.deadline_utc, now)
  return (
    <section className="case-header sticky" aria-label={t('header.summary')}>
      <div>
        <h1>{detail.merchant_name}</h1>
        <div className="case-id">{t('header.dispute', { id: detail.external_dispute_id })}</div>
        <div className="sub">
          {t('header.order')} <code>{detail.order_id}</code> ·{' '}
          {detailed && <>{t('header.transaction')} <code>{detail.transaction_id}</code> ·{' '}</>}
          {reasonLabel(detail.reason)}
        </div>
      </div>
      <dl className="facts-row">
        <div>
          <dt>{t('header.amountAtRisk')}</dt>
          <dd className="num amount">{detail.amount_display}</dd>
        </div>
        <div>
          <dt>{t('header.deadline')}</dt>
          <dd>
            {formatIst(detail.deadline_utc)}
            <div className={left <= 0 ? 'sub warn' : left < 6 * 3600 ? 'sub warn' : 'sub'} aria-live="off">
              {formatCountdown(left, true)}
            </div>
          </dd>
        </div>
        {detailed && <div>
          <dt>{t('header.workflow')}</dt>
          <dd>{stateLabel(detail.workflow_state)}</dd>
        </div>}
        {detailed && <div>
          <dt>{t('header.providerUpdate')}</dt>
          <dd>
            {detail.provider_status === 'NEW' ? t('header.noResponse') : detail.provider_status.replaceAll('_', ' ').toLowerCase()}{' '}
            <span className="sub">({detail.provider_status_raw ?? detail.provider_status})</span>
          </dd>
        </div>}
        {detail.debit_amount_paise !== null && (
          <div>
            <dt>{t('header.reportedDebit')}</dt>
            <dd>
              {inr(detail.debit_amount_paise)} <span className="sub">{t('header.providerReported')}</span>
            </dd>
          </div>
        )}
        {detailed && detail.dispute_utr && (
          <div>
            <dt>{t('header.utr')}</dt>
            <dd>
              <code>{detail.dispute_utr}</code> <span className="sub">{t('header.providerReported')}</span>
            </dd>
          </div>
        )}
        {detailed && detail.flags.length > 0 && (
          <div>
            <dt>{t('header.flags')}</dt>
            <dd>{detail.flags.join(', ')}</dd>
          </div>
        )}
      </dl>
    </section>
  )
}
