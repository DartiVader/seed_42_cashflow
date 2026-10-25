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
  /** компании, чьи строки приняты: для перехода к прогнозу после загрузки */
  companyIds?: string[]
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
  /** шаги расчёта, если запрошены trace: true и ML их отдаёт */
  trace?: TraceStep[] | TraceReport
}

/** Шаг «Как посчитано» из ML (README_SERVICE.md, «trace»): только агрегаты, ключи values могут добавляться */
export interface TraceStep {
  step: number
  name: string
  /** время шага, мс; null — шаг посчитан вместе с соседним */
  ms: number | null
  values: Record<string, unknown>
}

export interface TraceReport {
  steps: TraceStep[]
  took_ms?: number
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
  trace?: boolean
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

export interface DatasetFileReport extends Omit<ImportReport, 'fileType'> {
  name: string
  fileType: ImportFileType | null
  /** файл не загружен целиком: неверный формат, не CSV и т. п. */
  error?: string
}

export interface DatasetReport {
  files: DatasetFileReport[]
  companies: number
  operations: number
  skipped: number
  rejected: number
  failedFiles: number
  companyIds: string[]
  tookMs: number
}

export interface QualityMetrics {
  accuracy?: number
  precision?: number
  recall?: number
  f1?: number
  roc_auc?: number
  brier?: number
  confusion?: { tp: number, fp: number, fn: number, tn: number }
}

export interface QualityHorizon {
  horizon: number
  mae?: number
  mse?: number
  rmse?: number
  coverage_p10_p90?: number
}

export interface QualitySummary {
  model_version?: string
  generated_at?: string
  classification?: { shortfall?: QualityMetrics, negative?: QualityMetrics }
  /** те же метрики на холдауте — компаниях, которых модель не видела при обучении */
  classification_holdout?: { shortfall?: QualityMetrics, negative?: QualityMetrics }
  regression?: QualityHorizon[]
  coverage?: { p10_p90?: number, target?: number }
  baselines?: Record<string, string | number | null>[]
  method?: { scheme?: string, companies?: number, origins?: number, holdout?: string, notes?: string }
}

export interface QualityTable {
  columns: string[]
  rows: (string | number | null)[][]
}

export interface QualityJob {
  id: string
  status: 'queued' | 'running' | 'done' | 'failed'
  progress?: number | null
  startedAt?: string | null
  finishedAt?: string | null
  error?: string | null
}

/** admin — по компаниям, загруженным администратором; dataset — контрольный прогон по датасету участников */
export type QualitySource = 'admin' | 'dataset'

export interface QualityReport {
  available: boolean
  kind?: QualitySource
  summary?: QualitySummary | null
  tables?: Record<string, QualityTable>
  images?: string[]
  generatedAt?: string | null
  /** отчёт посчитан по компаниям, загруженным администраторами */
  source?: { companies?: number | null, computedAt?: string | null } | null
  job?: QualityJob | null
  canRun?: boolean
}

export type Marketplace = 'ozon' | 'wb' | 'yandex'

export interface MarketplaceSyncResult {
  dateFrom: string
  dateTo: string
  total: number
  accepted: number
  skipped: number
  rejected: number
  errors?: ImportError[]
  classifying?: boolean
}

export interface MarketplaceConnection {
  id: number
  companyId: string
  marketplace: Marketplace
  marketplaceName: string
  /** ключ наружу не отдаётся — только последние 4 символа */
  keyMasked: string
  clientId?: string | null
  businessId?: string | null
  lastSyncAt?: string | null
  lastResult?: MarketplaceSyncResult | null
  createdAt: string
}

export interface MarketplaceConnectRequest {
  companyId: string
  marketplace: Marketplace
  clientId?: string
  apiKey?: string
  token?: string
  businessId?: string
}
