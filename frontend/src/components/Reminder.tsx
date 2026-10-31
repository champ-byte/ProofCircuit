import { useTranslation } from 'react-i18next'
import { formatIst } from '../format'
import i18n from '../i18n'
import type { TaskReminderView } from '../types/api'
import { useView } from '../view'

const reason = (code: string | null) =>
  !code
    ? i18n.t('reminder.reasons.none')
    : i18n.exists(`reminder.reasons.${code}`)
      ? i18n.t(`reminder.reasons.${code}`)
      : code.replaceAll('_', ' ')

/** One line per state. n8n only schedules: "sent" always means the local in-app inbox, never WhatsApp. */
export function ReminderStatus({ reminder, onRetry }: { reminder: TaskReminderView | null; onRetry?: () => void }) {
  const { t } = useTranslation()
  const { detailed } = useView()
  if (!reminder) return null
  const trig = reminder.trigger
  return (
    <ul className="reminder-status" aria-label={t('reminder.label')}>
      {trig?.status === 'pending' && <li>{t('reminder.pending')}</li>}
      {trig?.status === 'delivered' && (
        <li>{t('reminder.scheduled', { time: trig.remind_at ? formatIst(trig.remind_at) : t('reminder.nextTime') })}</li>
      )}
      {trig?.status === 'skipped' && <li>{t('reminder.notScheduled', { reason: reason(trig.error) })}</li>}
      {(trig?.status === 'failed' || trig?.status === 'paused') && (
        <li className="warn">
          {t('reminder.failed')}{' '}
          {onRetry && (
            <button type="button" onClick={onRetry}>
              {t('reminder.retry')}
            </button>
          )}
          {detailed && <details><summary>{t('reminder.technical')}</summary>{trig.label ?? 'Reminder scheduling unavailable'}: {trig.error ?? 'unknown error'} ({trig.attempts} attempts)</details>}
        </li>
      )}
      {reminder.reminders.map((r) => (
        <li key={r.reminder_id}>
          {r.status === 'sent' && t('reminder.sent')}
          {r.status === 'queued' && t('reminder.queued')}
          {r.status === 'skipped' && t('reminder.skipped', { reason: reason(r.reason) })}
        </li>
      ))}
    </ul>
  )
}
