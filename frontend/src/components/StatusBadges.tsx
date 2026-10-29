import type { ReasoningMode } from '../types/api'

// Persistent honesty labels (PRD 13.2). Text carries meaning; color is decoration only.
export function StatusBadges({ mode }: { mode: ReasoningMode | null }) {
  return (
    <ul className="badges" aria-label="Environment labels">
      <li className="badge badge-neutral">Synthetic data</li>
      <li className="badge badge-neutral">Paytm simulator</li>
      <li className={`badge ${mode?.mode === 'live' ? 'badge-accent' : 'badge-warn'}`}>
        Reasoning: {mode ? mode.label : 'checking…'}
      </li>
    </ul>
  )
}
