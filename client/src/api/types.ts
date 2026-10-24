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
