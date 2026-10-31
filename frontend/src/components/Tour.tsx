import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'
import { speak, stopSpeaking, tourPage, type TourPage } from '../guide'

const TARGETS: Record<TourPage, string[]> = {
  landing: ['.landing-hero', '.mainnav', '.landing-actions'],
  cases: ['.queue-panel', '.queue-heading-actions', '.queue-table-wrap'],
  case: ['.case-progress', '.case-guide', '.assistant-card', '.case-tabs', '[data-testid=status-banner]'],
  staff: ['.staff-page-head', '.reply', '.staff-voice'],
}

/** Step-by-step guide for the current page; highlights each part and can read the text aloud. */
export function Tour({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const location = useLocation()
  const page = tourPage(location.pathname) ?? 'landing'
  const total = TARGETS[page].length
  const [index, setIndex] = useState(0)
  const [noVoice, setNoVoice] = useState(false)
  const step = Math.min(index, total - 1)
  const title = t(`tour.${page}.t${step + 1}`)
  const text = t(`tour.${page}.x${step + 1}`)
  const lang = i18n.resolvedLanguage ?? 'en'

  useEffect(() => {
    const el = document.querySelector(TARGETS[page][step])
    el?.classList.add('tour-highlight')
    el?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
    return () => el?.classList.remove('tour-highlight')
  }, [page, step])
  useEffect(() => () => stopSpeaking(), [])

  const close = () => {
    stopSpeaking()
    onClose()
  }

  return (
    <aside className="tour" role="dialog" aria-labelledby="tour-title" aria-describedby="tour-text" onKeyDown={(e) => e.key === 'Escape' && close()}>
      <div className="tour-head">
        <span className="eyebrow">{t('tour.title')} · {t('tour.step', { n: step + 1, total })}</span>
        <button type="button" className="link" onClick={close} aria-label={t('tour.close')}>✕</button>
      </div>
      <h2 id="tour-title">{title}</h2>
      <p id="tour-text">{text}</p>
      {noVoice && <p className="sub" role="status">{t('tour.noVoice')}</p>}
      <div className="tour-actions">
        <button type="button" onClick={() => setNoVoice(!speak(`${title}. ${text}`, lang))}>🔊 {t('tour.readAloud')}</button>
        <span className="tour-nav">
          <button type="button" disabled={step === 0} onClick={() => { stopSpeaking(); setNoVoice(false); setIndex(step - 1) }}>{t('tour.back')}</button>
          {step < total - 1 ? (
            <button type="button" className="button-primary" autoFocus onClick={() => { stopSpeaking(); setNoVoice(false); setIndex(step + 1) }}>{t('tour.next')}</button>
          ) : (
            <button type="button" className="button-primary" onClick={close}>{t('tour.done')}</button>
          )}
        </span>
      </div>
    </aside>
  )
}
