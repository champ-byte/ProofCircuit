import { createContext, useContext } from 'react'

// Simple view (the default) hides technical detail: hashes, code points, rule IDs, model names,
// tool names, the reconciliation trail and extracted-fact tables. Detailed view shows everything.
export const VIEW_KEY = 'proofsaathi.view'

export interface ViewState {
  detailed: boolean
  setDetailed: (detailed: boolean) => void
}

export const ViewContext = createContext<ViewState>({ detailed: false, setDetailed: () => undefined })

export function useView(): ViewState {
  return useContext(ViewContext)
}

export function savedDetailed(): boolean {
  try {
    return localStorage.getItem(VIEW_KEY) === 'detailed'
  } catch {
    return false
  }
}
