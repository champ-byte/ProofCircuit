import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { Tabs } from '../components/DemoDrawer'
import { HighlightedPage } from '../components/Evidence'
import { ConcessionModal } from '../components/Reviewer'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('HighlightedPage', () => {
  it('highlights backend code-point spans in Devanagari and emoji text and focuses the cited one', () => {
    const text = 'पावती 😀 ऑर्डर क्रमांक: ORD-DEMO-18500\nDelivered On: 31-Dec-2029'
    const cp = Array.from(text)
    const start = cp.indexOf('O')
    const spans = [
      { id: 'f1', start, end: start + 'ORD-DEMO-18500'.length, field: 'order_id' },
      { id: 'f2', start: cp.length - 11, end: cp.length, field: 'delivered_on' },
    ]
    const { container } = render(<HighlightedPage text={text} spans={spans} focusId="f1" />)
    const marks = container.querySelectorAll('mark')
    expect(Array.from(marks).map((m) => m.textContent)).toEqual(['ORD-DEMO-18500', '31-Dec-2029'])
    expect(document.activeElement).toBe(marks[0])
    expect(container.textContent).toBe(text)
  })

  it('skips out-of-range or overlapping spans instead of corrupting the text', () => {
    const { container } = render(
      <HighlightedPage
        text="abc"
        spans={[
          { id: 'a', start: 0, end: 2, field: 'x' },
          { id: 'b', start: 1, end: 3, field: 'y' },
          { id: 'c', start: 2, end: 9, field: 'z' },
        ]}
      />,
    )
    expect(container.textContent).toBe('abc')
    expect(container.querySelectorAll('mark')).toHaveLength(1)
  })
})

describe('ConcessionModal', () => {
  it('requires an explanation, a recorded approval and the typed word before conceding', async () => {
    const review = vi.spyOn(api, 'review').mockResolvedValue({
      approval_id: 'appr-1',
      expires_at: '2030-01-02T04:45:00Z',
      consequence: 'Conceding gives up the defense.',
    })
    const concede = vi.spyOn(api, 'concede').mockResolvedValue({ submission_id: 's1' })
    const onDone = vi.fn().mockResolvedValue(undefined)
    render(<ConcessionModal caseId="c1" token="t" amount="₹18,500.00" onClose={() => undefined} onDone={onDone} />)
    expect(screen.getByRole('dialog').textContent).toContain('₹18,500.00')
    const step1 = screen.getByRole('button', { name: /Step 1/ })
    expect(step1).toHaveProperty('disabled', true)
    fireEvent.change(screen.getByLabelText(/Reviewer explanation/), { target: { value: 'Customer proof is credible.' } })
    fireEvent.click(step1)
    const step2 = await screen.findByRole('button', { name: /Step 2/ })
    expect(review).toHaveBeenCalledWith('t', 'c1', {
      decision: 'approve_concession',
      explanation: 'Customer proof is credible.',
    })
    expect(step2).toHaveProperty('disabled', true)
    const confirm = screen.getByLabelText(/Type CONCEDE/)
    fireEvent.change(confirm, { target: { value: 'concede' } })
    expect(step2).toHaveProperty('disabled', true) // case-sensitive exact word
    fireEvent.change(confirm, { target: { value: 'CONCEDE' } })
    expect(step2).toHaveProperty('disabled', false)
    expect(concede).not.toHaveBeenCalled()
    fireEvent.click(step2)
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(concede).toHaveBeenCalledWith('t', 'c1', 'appr-1')
  })

  it('closes on Escape without conceding', () => {
    const concede = vi.spyOn(api, 'concede')
    const onClose = vi.fn()
    render(<ConcessionModal caseId="c1" token="t" amount="₹1.00" onClose={onClose} onDone={vi.fn()} />)
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
    expect(concede).not.toHaveBeenCalled()
  })
})

describe('Tabs', () => {
  it('supports arrow keys, Home and End', () => {
    const onChange = vi.fn()
    render(<Tabs active="inbox" onChange={onChange} />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(6)
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(tabs[1].tabIndex).toBe(-1)
    fireEvent.keyDown(tabs[0], { key: 'ArrowRight' })
    expect(onChange).toHaveBeenLastCalledWith('faults')
    fireEvent.keyDown(tabs[0], { key: 'ArrowLeft' })
    expect(onChange).toHaveBeenLastCalledWith('resume')
    fireEvent.keyDown(tabs[0], { key: 'End' })
    expect(onChange).toHaveBeenLastCalledWith('resume')
    fireEvent.keyDown(tabs[0], { key: 'Home' })
    expect(onChange).toHaveBeenLastCalledWith('inbox')
  })
})
