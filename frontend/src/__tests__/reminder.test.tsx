import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReminderStatus } from '../components/Reminder'
import type { TaskReminderView } from '../types/api'

afterEach(cleanup)

const trigger = (over: Partial<NonNullable<TaskReminderView['trigger']>> = {}): TaskReminderView['trigger'] => ({
  id: 'ev1',
  status: 'delivered',
  remind_at: '2030-01-02T04:32:00Z',
  attempts: 1,
  error: null,
  label: null,
  ...over,
})

describe('ReminderStatus', () => {
  it('renders nothing when reminders are off', () => {
    const { container } = render(<ReminderStatus reminder={null} />)
    expect(container.textContent).toBe('')
  })

  it('shows the scheduled time in IST once n8n acknowledged the trigger', () => {
    render(<ReminderStatus reminder={{ trigger: trigger(), reminders: [] }} />)
    expect(screen.getByText(/Reminder scheduled by n8n for/).textContent).toContain('10:02')
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('labels exhausted scheduling as unavailable and offers the explicit retry', () => {
    const onRetry = vi.fn()
    render(
      <ReminderStatus
        reminder={{
          trigger: trigger({ status: 'failed', error: 'HTTP 503', attempts: 3, label: 'Reminder scheduling unavailable' }),
          reminders: [],
        }}
        onRetry={onRetry}
      />,
    )
    expect(screen.getByText(/Reminder scheduling unavailable: HTTP 503 \(3 attempts\)/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Retry reminder scheduling' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('says a sent reminder went to the local inbox and explains skipped callbacks', () => {
    render(
      <ReminderStatus
        reminder={{
          trigger: trigger(),
          reminders: [
            { reminder_id: 'r1', status: 'sent', reason: null, message_id: 'm1', reminder_number: 1, created_at: '' },
            {
              reminder_id: 'r2',
              status: 'skipped',
              reason: 'task_responded',
              message_id: null,
              reminder_number: 1,
              created_at: '',
            },
          ],
        }}
      />,
    )
    expect(screen.getByText('Reminder sent to the staff inbox (n8n callback; no WhatsApp)')).toBeTruthy()
    expect(screen.getByText('n8n callback skipped: staff already responded')).toBeTruthy()
  })
})
