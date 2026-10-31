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
      {t?.status === 'pending' && <li>Scheduling a staff reminder…</li>}
      {t?.status === 'delivered' && (
        <li>Staff reminder scheduled for {t.remind_at ? formatIst(t.remind_at) : 'the next reminder time'}</li>
      )}
      {t?.status === 'skipped' && <li>Reminder not scheduled: {reason(t.error)}</li>}
      {(t?.status === 'failed' || t?.status === 'paused') && (
        <li className="warn">
          Reminder could not be scheduled. Staff can still reply in the inbox.{' '}
          {onRetry && (
            <button type="button" onClick={onRetry}>
              Try reminder again
            </button>
          )}
          <details><summary>Technical details</summary>{t.label ?? 'Reminder scheduling unavailable'}: {t.error ?? 'unknown error'} ({t.attempts} attempts)</details>
        </li>
      )}
      {reminder.reminders.map((r) => (
        <li key={r.reminder_id}>
          {r.status === 'sent' && 'Reminder sent to the staff inbox'}
          {r.status === 'queued' && 'Checking the reminder before sending'}
          {r.status === 'skipped' && `Reminder skipped: ${reason(r.reason)}`}
        </li>
      ))}
    </ul>
  )
}
