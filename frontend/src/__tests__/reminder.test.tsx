import type { ReactElement, ReactNode } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReminderStatus } from '../components/Reminder'
import type { TaskReminderView } from '../types/api'
import { ViewContext } from '../view'

const Detailed = ({ children }: { children: ReactNode }) => (
  <ViewContext.Provider value={{ detailed: true, setDetailed: () => undefined }}>{children}</ViewContext.Provider>
)
const renderDetailed = (ui: ReactElement) => render(ui, { wrapper: Detailed })

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
  it('hides the technical failure details in simple view', () => {
    render(<ReminderStatus reminder={{ trigger: trigger({ status: 'failed', error: 'HTTP 503', attempts: 3 }), reminders: [] }} />)
    expect(screen.getByText(/Reminder could not be scheduled/)).toBeTruthy()
    expect(screen.queryByText(/HTTP 503/)).toBeNull()
  })

  it('renders nothing when reminders are off', () => {
    const { container } = renderDetailed(<ReminderStatus reminder={null} />)
    expect(container.textContent).toBe('')
  })

  it('shows the scheduled time in IST once n8n acknowledged the trigger', () => {
    renderDetailed(<ReminderStatus reminder={{ trigger: trigger(), reminders: [] }} />)
    expect(screen.getByText(/Staff reminder scheduled for/).textContent).toContain('10:02')
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('labels exhausted scheduling as unavailable and offers the explicit retry', () => {
    const onRetry = vi.fn()
    renderDetailed(
      <ReminderStatus
        reminder={{
          trigger: trigger({ status: 'failed', error: 'HTTP 503', attempts: 3, label: 'Reminder scheduling unavailable' }),
          reminders: [],
        }}
        onRetry={onRetry}
      />,
    )
    expect(screen.getByText(/Reminder could not be scheduled/)).toBeTruthy()
    expect(screen.getByText(/Reminder scheduling unavailable: HTTP 503 \(3 attempts\)/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Try reminder again' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('says a sent reminder went to the local inbox and explains skipped callbacks', () => {
    renderDetailed(
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
    expect(screen.getByText('Reminder sent to the staff inbox')).toBeTruthy()
    expect(screen.getByText('Reminder skipped: staff already responded')).toBeTruthy()
  })
})
