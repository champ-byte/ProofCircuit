// Helpers shared by the welcome chooser, case progress and guided tour (kept out of component
// files so React fast refresh keeps working).

const ONBOARDED_KEY = 'proofsaathi.onboarded'

export function isOnboarded(): boolean {
  try {
    return localStorage.getItem(ONBOARDED_KEY) === '1'
  } catch {
    return false
  }
}

export function markOnboarded() {
  try {
    localStorage.setItem(ONBOARDED_KEY, '1')
  } catch {
    /* private mode: the chooser simply shows again next visit */
  }
}

const COLLECT = ['NEW', 'COLLECTING', 'WAITING_FOR_EVIDENCE', 'NEEDS_HUMAN_REVIEW']
const SEND = ['READY_TO_SUBMIT', 'SUBMITTING', 'SUBMISSION_UNCERTAIN']

/** Index of the current stage: 0 collect proof, 1 check and send, 2 result (3 when closed = all done). */
export function stageIndex(workflowState: string): number {
  if (COLLECT.includes(workflowState)) return 0
  if (SEND.includes(workflowState)) return 1
  if (workflowState === 'CLOSED') return 3
  return 2
}

export type TourPage = 'landing' | 'cases' | 'case' | 'staff'

export function tourPage(pathname: string): TourPage | null {
  if (pathname === '/') return 'landing'
  if (pathname === '/cases' || pathname === '/dashboard') return 'cases'
  if (pathname.startsWith('/cases/')) return 'case'
  if (pathname === '/staff') return 'staff'
  return null
}

/** Speak with the browser's own voices (no network). Returns false when no voice fits the language. */
export function speak(text: string, lang: string): boolean {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return false
  const voices = window.speechSynthesis.getVoices()
  const voice = voices.find((v) => v.lang.toLowerCase().startsWith(lang)) ?? null
  if (!voice && lang !== 'en') return false
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = voice?.lang ?? `${lang}-IN`
  if (voice) utterance.voice = voice
  window.speechSynthesis.speak(utterance)
  return true
}

export function stopSpeaking() {
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel()
}
