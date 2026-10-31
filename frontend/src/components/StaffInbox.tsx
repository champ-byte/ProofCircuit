import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { formatIst } from '../format'
import type { DemoSession, FixtureInfo, InboxView } from '../types/api'
import { ReminderStatus } from './Reminder'
import { StaffVoiceNotes } from './Testimony'

export type Runner = (fn: () => Promise<unknown>, ok: string) => Promise<void>

/** What one staff member sees for one case: requests, messages, reply box, uploads, voice notes. */
export function StaffInbox({
  caseId,
  staff,
  staffHandle,
  setStaffHandle,
  version,
  run,
  operator,
}: {
  caseId: string
  staff: DemoSession
  staffHandle?: string
  setStaffHandle?: (h: string) => void
  version: number
  run: Runner
  operator?: DemoSession | null
}) {
  const { t } = useTranslation()
  const [inbox, setInbox] = useState<InboxView | null>(null)
  const [fixtures, setFixtures] = useState<FixtureInfo[]>([])
  const [text, setText] = useState('')
  useEffect(() => {
    api.inbox(staff.token, caseId).then(setInbox).catch(() => setInbox(null))
    api.fixtures(staff.token, caseId).then(setFixtures).catch(() => setFixtures([]))
  }, [staff.token, caseId, version])
  const name = staff.user.display_name
  const mine = (inbox?.messages ?? []).filter((m) => m.to === name || m.from === name)
  return (
    <div className="staff-inbox">
      {setStaffHandle && (
        <label className="field">
          {t('staff.actingAs')}
          <select value={staffHandle} onChange={(e) => setStaffHandle(e.target.value)}>
            <option value="staff-delivery">Sanjay (Delivery, mr-IN)</option>
            <option value="staff-billing">Meera (Billing, hi-IN)</option>
          </select>
        </label>
      )}
      <ul className="timeline">
        {(inbox?.tasks ?? [])
          .filter((task) => task.kind === 'evidence' && task.assignee === name)
          .map((task) => (
            <li key={task.id}>
              {t('staff.task', {
                what: t(`requirements.${task.requirement_id}`, { defaultValue: task.requirement_id.replaceAll('_', ' ') }),
                round: task.round,
                status: t(`staff.taskStatus.${task.status}`, { defaultValue: task.status }),
              })}
              <ReminderStatus
                reminder={task.reminder}
                onRetry={
                  operator && task.reminder?.trigger
                    ? () =>
                        void run(
                          () => api.retryReminderTrigger(operator.token, caseId, task.reminder!.trigger!.id),
                          'Reminder scheduling retried with the same trigger identity.',
                        )
                    : undefined
                }
              />
            </li>
          ))}
      </ul>
      <ul className="messages" aria-label={t('staff.messagesFor', { name })}>
        {mine.length === 0 && <li className="sub">{t('staff.noMessages', { name })}</li>}
        {mine.map((m) => (
          <li key={m.id} className={`msg msg-${m.direction}`} lang={m.locale.split('-')[0]}>
            <div className="sub">
              {m.direction === 'outbound' ? t('staff.fromApp') : t('staff.from', { name: m.from })} · {formatIst(m.created_at)} ·{' '}
              {m.delivery_state.replaceAll('_', ' ')}
            </div>
            {m.body}
          </li>
        ))}
      </ul>
      <form
        className="reply"
        onSubmit={(e) => {
          e.preventDefault()
          if (!text.trim()) return
          void run(async () => {
            await api.reply(staff.token, caseId, text.trim())
            setText('')
          }, t('staff.replied'))
        }}
      >
        <label>
          {t('staff.replyAs', { name })}
          <input value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <button type="submit">{t('staff.send')}</button>
      </form>
      <div className="fixture-buttons">
        <span className="sub">{t('staff.uploadAs', { name })}</span>
        {fixtures
          .filter((f) => f.name !== 'invoice')
          .map((f) => (
            <button
              key={f.name}
              type="button"
              onClick={() =>
                run(async () => {
                  const blob = await api.fixtureFile(staff.token, caseId, f.name)
                  await api.upload(staff.token, caseId, blob, f.filename)
                }, t('staff.uploaded', { file: f.filename, name }))
              }
            >
              {t('staff.upload', { name: t(`staff.fixtures.${f.name}`, { defaultValue: f.name.replaceAll('_', ' ') }) })}
            </button>
          ))}
      </div>
      <StaffVoiceNotes caseId={caseId} staff={staff} version={version} run={run} />
    </div>
  )
}
