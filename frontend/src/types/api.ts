export interface ReasoningMode {
  mode: 'live' | 'manual' | 'fixture_replay'
  label: string
}

export interface ProviderReadiness {
  name: string
  role: string
  status: string
  model: string | null
  detail: string
  notes: string[]
}

export interface ProviderReport {
  reasoning_mode: ReasoningMode
  reasoners: ProviderReadiness[]
  integrations: ProviderReadiness[]
  synthetic_data: boolean
  paytm_mode: string
}

export interface DemoUser {
  mid: string
  merchant_name: string
  handle: string
  display_name: string
  role: string
  locale: string
}

export interface DemoSession {
  token: string
  user: { handle: string; display_name: string; role: string; locale: string }
  merchant: { name: string; mid: string }
}

export interface CaseSummary {
  id: string
  merchant_name: string
  mid: string
  external_dispute_id: string
  order_id: string
  transaction_id: string
  reason: string
  amount_paise: number
  amount_display: string
  currency: string
  debit_amount_paise: number | null
  dispute_utr: string | null
  deadline_utc: string
  deadline_local: string
  deadline_raw: string
  timezone_assumption: string
  seconds_to_deadline: number
  deadline_expired: boolean
  workflow_state: string
  provider_status: string
  provider_status_raw: string | null
  flags: string[]
  version: number
  owner: string | null
  next_action: string
  synthetic: boolean
}
