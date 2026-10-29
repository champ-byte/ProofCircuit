import type { TranscriptView } from './types/api'

export function formatMs(ms: number): string {
  const total = Math.floor(ms / 100) / 10
  const m = Math.floor(total / 60)
  const s = (total - m * 60).toFixed(1).padStart(4, '0')
  return `${m}:${s}`
}

/** How the text was produced; human-written text is never presented as speech-to-text. */
export function methodLabel(t: TranscriptView): string {
  if (t.method === 'stt') return `Speech-to-text (${t.provider ?? 'unknown'} · ${t.model ?? 'unknown model'})`
  if (t.method === 'staff_correction') return `Corrected by ${t.author ?? 'staff'} (not speech-to-text)`
  return `Human transcription typed by ${t.author ?? 'staff'} (not speech-to-text)`
}

export function confirmationLabel(t: TranscriptView, speaker: string): string {
  if (t.confirmation_state === 'confirmed') return `Confirmed by ${t.confirmed_by ?? speaker}`
  if (t.confirmation_state === 'superseded') return 'Superseded by a later version'
  return `Unconfirmed — waiting for ${speaker} to check it`
}
