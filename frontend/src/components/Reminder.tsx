import { formatIst } from '../format'
import type { TaskReminderView } from '../types/api'

const REASONS: Record<string, string> = {
  not_due: 'not due yet',
  task_responded: 'staff already responded',
  staff_replied: 'staff already replied',
  superseded: 'a newer request replaced this one',
  round_changed: 'the request round changed',
  deadline_passed: 'the response deadline has passed',
}

const reason = (code: string | null) => (code ? (REASONS[code] ?? code.replaceAll('_', ' ')) : 'no reason given')

/** One line per state. n8n only schedules: "sent" always means the local in-app inbox, never WhatsApp. */
export function ReminderStatus({ reminder, onRetry }: { reminder: TaskReminderView | null; onRetry?: () => void }) {
  if (!reminder) return null
  const t = reminder.trigger
  return (
    <ul className="reminder-status" aria-label="Staff reminder">
      {t?.status === 'pending' && <li>Reminder: scheduling with n8n…</li>}
      {t?.status === 'delivered' && (
        <li>Reminder scheduled by n8n for {t.remind_at ? formatIst(t.remind_at) : 'the configured delay'}</li>
      )}
      {t?.status === 'skipped' && <li>Reminder not scheduled: {reason(t.error)}</li>}
      {(t?.status === 'failed' || t?.status === 'paused') && (
        <li className="warn">
          {t.label ?? 'Reminder scheduling unavailable'}: {t.error ?? 'unknown error'} ({t.attempts} attempt
          {t.attempts === 1 ? '' : 's'}){' '}
          {onRetry && (
            <button type="button" onClick={onRetry}>
              Retry reminder scheduling
            </button>
          )}
        </li>
      )}
      {reminder.reminders.map((r) => (
        <li key={r.reminder_id}>
          {r.status === 'sent' && 'Reminder sent to the staff inbox (n8n callback; no WhatsApp)'}
          {r.status === 'queued' && 'n8n callback received; rechecking before sending'}
          {r.status === 'skipped' && `n8n callback skipped: ${reason(r.reason)}`}
        </li>
      ))}
    </ul>
  )
}
