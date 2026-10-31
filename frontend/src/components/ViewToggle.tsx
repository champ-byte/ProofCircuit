import { type ReactNode, useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { savedDetailed, useView, VIEW_KEY, ViewContext } from '../view'

export function ViewProvider({ children }: { children: ReactNode }) {
  const [detailed, setState] = useState(savedDetailed)
  const setDetailed = useCallback((next: boolean) => {
    setState(next)
    try {
      localStorage.setItem(VIEW_KEY, next ? 'detailed' : 'simple')
    } catch {
      /* private mode: the choice lasts until reload */
    }
  }, [])
  return <ViewContext.Provider value={{ detailed, setDetailed }}>{children}</ViewContext.Provider>
}

/** Header switch: two pressed-state buttons, so screen readers announce the current view. */
export function ViewToggle() {
  const { t } = useTranslation()
  const { detailed, setDetailed } = useView()
  return (
    <div className="view-toggle" role="group" aria-label={t('view.label')}>
      <button type="button" aria-pressed={!detailed} onClick={() => setDetailed(false)}>{t('view.simple')}</button>
      <button type="button" aria-pressed={detailed} onClick={() => setDetailed(true)}>{t('view.detailed')}</button>
    </div>
  )
}
