import i18n from './i18n'
import type { TranscriptView } from './types/api'

export function formatMs(ms: number): string {
  const total = Math.floor(ms / 100) / 10
  const m = Math.floor(total / 60)
  const s = (total - m * 60).toFixed(1).padStart(4, '0')
  return `${m}:${s}`
}

/** How the text was produced; human-written text is never presented as speech-to-text. */
export function methodLabel(t: TranscriptView): string {
  const author = t.author ?? i18n.t('testimony.staffFallback')
  if (t.method === 'stt')
    return i18n.t('testimony.method.stt', { provider: t.provider ?? i18n.t('testimony.unknown'), model: t.model ?? i18n.t('testimony.unknownModel') })
  if (t.method === 'staff_correction') return i18n.t('testimony.method.staff_correction', { author })
  return i18n.t('testimony.method.human', { author })
}

export function confirmationLabel(t: TranscriptView, speaker: string): string {
  if (t.confirmation_state === 'confirmed') return i18n.t('testimony.confirmation.confirmed', { name: t.confirmed_by ?? speaker })
  if (t.confirmation_state === 'superseded') return i18n.t('testimony.confirmation.superseded')
  return i18n.t('testimony.confirmation.unconfirmed', { name: speaker })
}
