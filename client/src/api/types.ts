export interface ApiError {
  field: string | null
  message: string
}

export interface ApiResponse<T> {
  localDateTime: string
  methodName: string
  success: boolean
  data: T
  listErrors: ApiError[]
}

export interface User {
  id: number
  email: string
  isAdmin: boolean
}

export interface Auth {
  expiresAt: string
  user: User
}

export type ImportFileType = 'COMPANIES' | 'OPERATIONS'

export interface ImportError {
  lineNumber: number
  message: string
}

export interface ImportReport {
  fileType: ImportFileType
  total: number
  accepted: number
  skipped: number
  rejected: number
  errors: ImportError[]
}

export type ListFilters = Record<string, string>

export interface Page<T> {
  items: T[]
  page: number
  size: number
  totalElements: number
  totalPages: number
}

export type LegalForm = 'ООО' | 'ИП'

export type Direction = 'Поступление' | 'Списание'

export interface Company {
  companyId: string
  companyName: string
  companyInn: string
  legalForm: LegalForm
  industry: string
}

export interface Operation {
  id: number
  companyId: string
  operationId: string
  date: string
  amount: number
  direction: Direction
  counterpartyInn: string | null
  counterpartyName: string
  paymentPurpose: string | null
}

export interface OperationPayload {
  companyId: string
  operationId: string
  date: string
  amount: string
  direction: Direction
  counterpartyInn: string
  counterpartyName: string
  paymentPurpose: string
}

export interface Credentials {
  email: string
  password: string
}

export type ForecastStatus = 'ok' | 'gap_expected' | 'already_negative' | 'below_cushion'

export type Periodicity = 'once' | 'monthly' | 'monthly_irregular' | 'quarterly' | 'bimonthly' | 'seasonal'

export interface DailyPoint {
  date: string
  p10: number
  p50: number
  p90: number
  p25?: number
  p75?: number
  prob_below?: number
  confidence?: string
}

export interface ForecastEvent {
  date: string
  amount: number
  category: string
  source: string
  confidence: number
  mandatory?: boolean
  stream_id?: string | null
  counterparty_name?: string | null
  overdue_from?: string | null
  label?: string | null
  periodicity?: Periodicity
}

export interface ActionCategory {
  name: string
  amount: number
}

export interface ActionDetail {
  type: string
  stream_id?: string | null
  category?: string | null
  counterparty_name?: string | null
  amount?: number
  amount_high?: number
  date_from?: string | null
  date_to?: string | null
  prob_before?: number
  prob_after?: number
  prob_window_before?: number
  prob_window_after?: number
  prob_horizon_after?: number
  shortfall_before?: number
  shortfall_after?: number
  gap_date_after?: string | null
  categories?: ActionCategory[]
}

export interface Gap {
  date: string
  probability: number
  shortfall: number
  shortfall_low?: number
  shortfall_high?: number
  shortfall_at_gap?: number
  shortfall_at_gap_low?: number
  shortfall_at_gap_high?: number
  reasons: string[]
  actions: string[]
  actions_detail?: ActionDetail[]
}

export interface DataQuality {
  history_days?: number
  short_history?: boolean
  gaps_in_data?: number
  days_since_last_operation?: number
  industry_known?: boolean
}

export interface Forecast {
  company_id: string
  as_of: string
  model_version: string
  status: ForecastStatus
  balance_now?: number
  data_quality?: DataQuality
  daily: DailyPoint[]
  events: ForecastEvent[]
  gaps: Gap[]
}

export interface Scenario {
  revenue_multiplier?: number
  fixed_cost_multiplier?: number
  delay_counterparty?: Record<string, number>
  extra_expenses?: ForecastEvent[]
}

export interface ForecastRequest {
  asOf: string
  horizonDays?: number
  threshold?: number
  events?: ForecastEvent[]
  scenario?: Scenario | null
}

export type ExplainKind = 'summary' | 'gap' | 'scenario' | 'answer'

export interface ExplainRequest {
  kind: ExplainKind
  forecast: Forecast
  base?: Forecast | null
  question?: string | null
}

export interface Explanation {
  text: string
  source: 'llm' | 'template'
  verified: boolean
}

export type PlanFactStatus = 'paid' | 'partial' | 'missed'

export interface PlanFactDay {
  date: string
  plan_p10: number
  plan_p50: number
  plan_p90: number
  fact: number | null
  outside: boolean
}

export interface PlanFactEvent {
  date: string
  category: string
  amount_plan: number
  amount_fact: number | null
  status: PlanFactStatus
  days_late?: number | null
  stream_id?: string | null
  counterparty_name?: string | null
}

export interface PlanFactSummary {
  missed_in: number
  missed_out: number
  max_deviation: number
}

export interface PlanFact {
  as_of_plan: string
  as_of: string
  daily: PlanFactDay[]
  events: PlanFactEvent[]
  summary: PlanFactSummary
}
