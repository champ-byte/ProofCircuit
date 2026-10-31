import type { ReactElement, ReactNode } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { VoiceNoteCard } from '../components/Testimony'
import { confirmationLabel, formatMs, methodLabel } from '../testimony'
import { keySteps } from '../status'
import type { AuditEventView, DemoSession, TranscriptView, VoiceNoteView } from '../types/api'
import { ViewContext } from '../view'

const Detailed = ({ children }: { children: ReactNode }) => (
  <ViewContext.Provider value={{ detailed: true, setDetailed: () => undefined }}>{children}</ViewContext.Provider>
)
const renderDetailed = (ui: ReactElement) => render(ui, { wrapper: Detailed })

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const MR = 'मी आधी चुकीची पावती पाठवली होती.'

function transcript(over: Partial<TranscriptView> = {}): TranscriptView {
  return {
    id: 't1',
    version: 1,
    text: MR,
    text_sha256: 'x',
    text_recheck_ok: true,
    method: 'stt',
    provider: 'faster_whisper',
    model: 'small',
    language: 'mr',
    language_probability: 1,
    segments: [
      {
        start: 0,
        end: Array.from(MR).length,
        audio_start_ms: 4300,
        audio_end_ms: 9800,
        text: MR,
        recheck_ok: true,
        timestamp_in_range: true,
      },
    ],
    timestamps_available: true,
    author: null,
    confirmation_state: 'unconfirmed',
    confirmed_by: null,
    confirmed_at: null,
    created_at: '2030-01-02T04:30:00Z',
    ...over,
  }
}

function note(cur: TranscriptView | null, over: Partial<VoiceNoteView> = {}): VoiceNoteView {
  return {
    id: 'vn1',
    staff: 'Sanjay (Delivery)',
    staff_user_id: 'u1',
    staff_task: { id: 'task1', requirement_id: 'delivery_record', round: 2 },
    original_filename: 'voice.ogg',
    mime_type: 'audio/ogg',
    size_bytes: 27750,
    sha256: 'a'.repeat(64),
    locale: 'mr-IN',
    duration_ms: 11214,
    stt_status: cur ? 'transcribed' : 'stt_unavailable',
    stt_provider: null,
    stt_detail: null,
    created_at: '2030-01-02T04:30:00Z',
    note: 'Staff testimony, not a delivery document; it cannot satisfy a checklist item.',
    current: cur,
    versions: cur ? [cur] : [],
    ...over,
  }
}

const sanjay: DemoSession = {
  token: 'tok',
  user: {
    handle: 'staff-delivery',
    display_name: 'Sanjay (Delivery)',
    role: 'staff',
    locale: 'mr-IN',
  },
  merchant: { name: 'Metro Furniture Demo', mid: 'MID-DEMO-001' },
}
const meera: DemoSession = {
  ...sanjay,
  user: {
    ...sanjay.user,
    handle: 'staff-billing',
    display_name: 'Meera (Billing)',
  },
}

describe('testimony labels', () => {
  it('never presents human-written text as speech-to-text', () => {
    expect(methodLabel(transcript())).toBe('Speech-to-text (faster_whisper · small)')
    expect(methodLabel(transcript({ method: 'staff_correction', author: 'Sanjay' }))).toMatch(/not speech-to-text/)
    expect(methodLabel(transcript({ method: 'human_transcription', author: 'Sanjay' }))).toBe(
      'Human transcription typed by Sanjay (not speech-to-text)',
    )
  })
  it('states confirmation in words', () => {
    expect(confirmationLabel(transcript(), 'Sanjay')).toBe('Unconfirmed — waiting for Sanjay to check it')
    expect(confirmationLabel(transcript({ confirmation_state: 'confirmed', confirmed_by: 'Sanjay' }), 'Sanjay')).toBe(
      'Confirmed by Sanjay',
    )
  })
  it('formats audio offsets', () => {
    expect(formatMs(4300)).toBe('0:04.3')
    expect(formatMs(71200)).toBe('1:11.2')
  })
})

describe('VoiceNoteCard', () => {
  it('in simple view says it is not proof and hides the hash, file and method details', () => {
    vi.spyOn(api, 'voiceAudio').mockResolvedValue(new Blob())
    render(<VoiceNoteCard note={note(transcript())} token="tok" />)
    expect(screen.getByText(/It is not proof/)).toBeTruthy()
    expect(screen.getByText('Unconfirmed — waiting for Sanjay (Delivery) to check it')).toBeTruthy()
    expect(screen.queryByText(/SHA-256|faster_whisper|Transcript v1/)).toBeNull()
  })

  it('shows provenance, the testimony caveat and seekable segments; controls only for the speaker', () => {
    vi.spyOn(api, 'voiceAudio').mockResolvedValue(new Blob())
    const run = vi.fn(async () => {})
    const { rerender } = renderDetailed(<VoiceNoteCard note={note(transcript())} token="tok" speaker={meera} run={run} />)
    expect(screen.getByText(/not a delivery document/)).toBeTruthy()
    expect(screen.getByText(/answers delivery record request round 2/)).toBeTruthy()
    expect(screen.getByText('Unconfirmed — waiting for Sanjay (Delivery) to check it')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Play from 0:04.3' }).textContent).toBe('0:04.3–0:09.8')
    expect(screen.getByText(MR).closest('[lang]')?.getAttribute('lang')).toBe('mr')
    expect(screen.queryByText(/beyond the audio length/)).toBeNull()
    expect(screen.queryByRole('button', { name: /Confirm transcript/ })).toBeNull() // Meera did not record it

    rerender(<VoiceNoteCard note={note(transcript())} token="tok" speaker={sanjay} run={run} />)
    expect(screen.getByRole('button', { name: /Confirm transcript is what I said/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Correct transcript' })).toBeTruthy()
  })

  it('offers labelled human transcription when speech-to-text is unavailable, without timestamps', () => {
    vi.spyOn(api, 'voiceAudio').mockResolvedValue(new Blob())
    const run = vi.fn(async () => {})
    renderDetailed(<VoiceNoteCard note={note(null)} token="tok" speaker={sanjay} run={run} />)
    expect(screen.getByText('Speech-to-text unavailable')).toBeTruthy()
    expect(
      screen.getByRole('button', {
        name: 'Type what I said (human transcription)',
      }),
    ).toBeTruthy()

    cleanup()
    const typed = transcript({
      method: 'human_transcription',
      author: 'Sanjay',
      segments: [],
      timestamps_available: false,
    })
    renderDetailed(<VoiceNoteCard note={note(typed)} token="tok" />)
    expect(screen.getByText(/No audio timestamps for this version/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Play from/ })).toBeNull()
  })
})

describe('provider timestamps', () => {
  it('flags an impossible segment time instead of hiding or changing it', () => {
    vi.spyOn(api, 'voiceAudio').mockResolvedValue(new Blob())
    const seg = {
      start: 0,
      end: 3,
      audio_start_ms: 0,
      audio_end_ms: 27120,
      text: 'abc',
      recheck_ok: true,
      timestamp_in_range: false,
    }
    renderDetailed(<VoiceNoteCard note={note(transcript({ text: 'abc', segments: [seg] }))} token="tok" />)
    expect(screen.getByRole('button', { name: 'Play from 0:00.0' }).textContent).toBe('0:00.0–0:27.1')
    expect(screen.getByText(/beyond the audio length/)).toBeTruthy()
  })
})

describe('key steps', () => {
  it('includes the staff voice note and its confirmation', () => {
    const ev = (seq: number, event_type: string): AuditEventView =>
      ({
        seq,
        event_type,
        summary: event_type,
        actor_type: 'user',
        actor_id: null,
        data: {},
        created_at: '2030-01-02T04:30:00Z',
      }) as AuditEventView
    const labels = keySteps([
      ev(1, 'testimony.received'),
      ev(2, 'testimony.transcribed'),
      ev(3, 'testimony.confirmed'),
    ]).map((s) => s.label)
    expect(labels).toEqual(['Staff voice note', 'Voice note confirmed'])
  })
})
